#!/usr/bin/env bash
#
# Set up and deploy the AdVance Dispatch job.
#
#   deploy/deploy.sh setup              one-off infrastructure (plan section 9.1)
#   deploy/deploy.sh deploy             test, build, tag latest, update the job, publish templates
#   deploy/deploy.sh <command> --dry-run   say what would happen, change nothing
#   deploy/deploy.sh deploy --skip-tests   deploy without running pytest first
#
# `setup` is safe to run again: every step checks first and only creates what
# is missing. It makes:
#
#   1. The job's service account, advance-dispatch, with read access to gold
#      and the lookups, write access to the Dispatch bucket, Firestore, the
#      aws_ses secret, Cloud Scheduler (to delete its own trigger) and token
#      creation on itself (to sign browser links).
#   2. The invoker service account, advance-dispatch-invoker, that Scheduler
#      triggers run as, with run.invoker on the job.
#   3. Grants to the API's service account, advance-api, so it can manage
#      triggers, attach the invoker account to them, and run the job.
#   4. The Artifact Registry repository, keeping the newest 2 images.
#   5. The Cloud Run job, 2 GiB, 15 minute timeout, no retries.
#   6. The Firestore TTL policy on the `runs` collection group.
#   7. The lifecycle rule deleting `sent/` objects after 30 days.
#
# `deploy` runs the tests, builds the image with Cloud Build, moves `latest`
# onto it, points the job at `latest`, and runs `publish-templates`.

set -euo pipefail

# ---------------------------------------------------------------- #
# Configuration
# ---------------------------------------------------------------- #

PROJECT_ID='advance-campaign-app'
REGION='australia-southeast1'

JOB_NAME='advance-dispatch'
REPOSITORY='advance-dispatch'
IMAGE_NAME='dispatch'

JOB_ACCOUNT_NAME='advance-dispatch'
INVOKER_ACCOUNT_NAME='advance-dispatch-invoker'
API_ACCOUNT_NAME='advance-api'

JOB_ACCOUNT="${JOB_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
INVOKER_ACCOUNT="${INVOKER_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
API_ACCOUNT="${API_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

GOLD_BUCKET='advance_gold'
LOOKUPS_BUCKET='advance_lookups'
DISPATCH_BUCKET='advance_dispatch'
SES_SECRET='aws_ses'

# How many images the repository keeps
KEEP_IMAGES=2

# Days before archive objects are deleted
ARCHIVE_RETENTION_DAYS=30

IMAGE_PATH="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/${IMAGE_NAME}"
LATEST_IMAGE="${IMAGE_PATH}:latest"

COMMAND=''
DRY_RUN=false
RUN_TESTS=true

# ---------------------------------------------------------------- #
# Output
# ---------------------------------------------------------------- #

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '\033[33m    %s\033[0m\n' "$*"; }
die()  { printf '\033[31m\nError: %s\033[0m\n' "$*" >&2; exit 1; }

# Print a command instead of running it when this is a rehearsal
run() {
    if [[ "$DRY_RUN" == true ]]; then
        printf '    [dry run] %s\n' "$*"
    else
        "$@"
    fi
}

# ---------------------------------------------------------------- #
# Arguments
# ---------------------------------------------------------------- #

while [[ $# -gt 0 ]]; do
    case "$1" in
        setup|deploy) COMMAND="$1"; shift ;;
        --dry-run)    DRY_RUN=true; shift ;;
        --skip-tests) RUN_TESTS=false; shift ;;
        -h|--help)    sed -n '2,27p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *)            die "unknown argument: $1" ;;
    esac
done

[[ -n "$COMMAND" ]] || die 'say setup or deploy (see --help)'

# ---------------------------------------------------------------- #
# Preflight
# ---------------------------------------------------------------- #

step 'Preflight'

command -v gcloud >/dev/null || die 'gcloud is not on PATH'

# Run from the repository root whatever directory this was invoked from
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
[[ -f Dockerfile ]] || die "no Dockerfile at ${REPO_ROOT}"

ACCOUNT="$(gcloud config get-value account 2>/dev/null || true)"
if [[ -z "$ACCOUNT" || "$ACCOUNT" == '(unset)' ]]; then
    die 'not authenticated: run gcloud auth login'
fi

info "Command:  ${COMMAND}"
info "Account:  ${ACCOUNT}"
info "Project:  ${PROJECT_ID}"
info "Job:      ${JOB_NAME} (${REGION})"
info "Image:    ${IMAGE_PATH}"

if [[ "$DRY_RUN" == true ]]; then
    warn 'Dry run: nothing will be created, built or changed.'
fi

# ---------------------------------------------------------------- #
# Setup helpers
# ---------------------------------------------------------------- #

# Create a service account unless it already exists
ensure_service_account() {
    local name="$1"
    local display_name="$2"
    local email="${name}@${PROJECT_ID}.iam.gserviceaccount.com"

    if gcloud iam service-accounts describe "$email" --project="$PROJECT_ID" >/dev/null 2>&1; then
        info "${email}: exists"
        return
    fi
    run gcloud iam service-accounts create "$name" \
        --project="$PROJECT_ID" \
        --display-name="$display_name"
}

# Grant a role on a bucket to a member
grant_bucket_role() {
    local bucket="$1"
    local member="$2"
    local role="$3"
    run gcloud storage buckets add-iam-policy-binding "gs://${bucket}" \
        --member="$member" --role="$role" --quiet >/dev/null
    info "${role} on gs://${bucket} -> ${member}"
}

# Grant a project-wide role to a member
grant_project_role() {
    local member="$1"
    local role="$2"
    run gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="$member" --role="$role" --condition=None --quiet >/dev/null
    info "${role} on project -> ${member}"
}

# Grant a role on a service account to a member
grant_account_role() {
    local account="$1"
    local member="$2"
    local role="$3"
    run gcloud iam service-accounts add-iam-policy-binding "$account" \
        --project="$PROJECT_ID" --member="$member" --role="$role" --quiet >/dev/null
    info "${role} on ${account} -> ${member}"
}

# Grant a role on the Cloud Run job to a member
grant_job_role() {
    local member="$1"
    local role="$2"
    run gcloud run jobs add-iam-policy-binding "$JOB_NAME" \
        --project="$PROJECT_ID" --region="$REGION" \
        --member="$member" --role="$role" --quiet >/dev/null
    info "${role} on job ${JOB_NAME} -> ${member}"
}

# ---------------------------------------------------------------- #
# Setup
# ---------------------------------------------------------------- #

do_setup() {
    step '1. The job service account'
    ensure_service_account "$JOB_ACCOUNT_NAME" 'AdVance Dispatch job'
    grant_bucket_role "$GOLD_BUCKET" "serviceAccount:${JOB_ACCOUNT}" 'roles/storage.objectViewer'
    grant_bucket_role "$LOOKUPS_BUCKET" "serviceAccount:${JOB_ACCOUNT}" 'roles/storage.objectViewer'
    grant_bucket_role "$DISPATCH_BUCKET" "serviceAccount:${JOB_ACCOUNT}" 'roles/storage.objectAdmin'
    grant_project_role "serviceAccount:${JOB_ACCOUNT}" 'roles/datastore.user'
    grant_project_role "serviceAccount:${JOB_ACCOUNT}" 'roles/cloudscheduler.admin'
    run gcloud secrets add-iam-policy-binding "$SES_SECRET" \
        --project="$PROJECT_ID" \
        --member="serviceAccount:${JOB_ACCOUNT}" \
        --role='roles/secretmanager.secretAccessor' --quiet >/dev/null
    info "roles/secretmanager.secretAccessor on ${SES_SECRET} -> ${JOB_ACCOUNT}"

    # Signing browser links goes through signBlob, which needs token creation on itself
    grant_account_role "$JOB_ACCOUNT" "serviceAccount:${JOB_ACCOUNT}" 'roles/iam.serviceAccountTokenCreator'

    step '2. The invoker service account'
    ensure_service_account "$INVOKER_ACCOUNT_NAME" 'AdVance Dispatch Scheduler invoker'

    step '3. The API service account'
    grant_project_role "serviceAccount:${API_ACCOUNT}" 'roles/cloudscheduler.admin'
    grant_account_role "$INVOKER_ACCOUNT" "serviceAccount:${API_ACCOUNT}" 'roles/iam.serviceAccountUser'

    step '4. The Artifact Registry repository'
    if gcloud artifacts repositories describe "$REPOSITORY" \
            --project="$PROJECT_ID" --location="$REGION" >/dev/null 2>&1; then
        info "${REPOSITORY}: exists"
    else
        run gcloud artifacts repositories create "$REPOSITORY" \
            --project="$PROJECT_ID" \
            --location="$REGION" \
            --repository-format=docker \
            --description='AdVance Dispatch job images'
    fi

    # Keep the newest images and delete the rest
    local policy_file
    policy_file="$(mktemp)"
    cat > "$policy_file" <<POLICY
[
  {"name": "keep-newest", "action": {"type": "Keep"}, "mostRecentVersions": {"keepCount": ${KEEP_IMAGES}}},
  {"name": "delete-rest", "action": {"type": "Delete"}, "condition": {"tagState": "ANY"}}
]
POLICY
    run gcloud artifacts repositories set-cleanup-policies "$REPOSITORY" \
        --project="$PROJECT_ID" --location="$REGION" \
        --policy="$policy_file" --no-dry-run
    rm -f "$policy_file"

    step '5. The Cloud Run job'
    if gcloud run jobs describe "$JOB_NAME" --project="$PROJECT_ID" --region="$REGION" >/dev/null 2>&1; then
        info "${JOB_NAME}: exists"
    else
        # The image must exist before the job can be created
        if ! gcloud artifacts docker images describe "$LATEST_IMAGE" --project="$PROJECT_ID" >/dev/null 2>&1; then
            warn "No image at ${LATEST_IMAGE} yet. Run 'deploy/deploy.sh deploy', then setup again."
        else
            run gcloud run jobs create "$JOB_NAME" \
                --project="$PROJECT_ID" \
                --region="$REGION" \
                --image="$LATEST_IMAGE" \
                --service-account="$JOB_ACCOUNT" \
                --memory=2Gi \
                --cpu=1 \
                --task-timeout=15m \
                --max-retries=0
        fi
    fi

    # The invoker runs the job; the API runs it with argument overrides
    if gcloud run jobs describe "$JOB_NAME" --project="$PROJECT_ID" --region="$REGION" >/dev/null 2>&1; then
        grant_job_role "serviceAccount:${INVOKER_ACCOUNT}" 'roles/run.invoker'
        grant_job_role "serviceAccount:${API_ACCOUNT}" 'roles/run.developer'
    else
        warn 'Job grants skipped until the job exists.'
    fi

    step '6. Firestore TTL on runs'
    run gcloud firestore fields ttls update expire_at \
        --project="$PROJECT_ID" \
        --database='(default)' \
        --collection-group=runs \
        --enable-ttl \
        --async

    step '7. Archive lifecycle'
    local lifecycle_file
    lifecycle_file="$(mktemp)"
    cat > "$lifecycle_file" <<LIFECYCLE
{"rule": [{"action": {"type": "Delete"}, "condition": {"age": ${ARCHIVE_RETENTION_DAYS}, "matchesPrefix": ["sent/"]}}]}
LIFECYCLE
    run gcloud storage buckets update "gs://${DISPATCH_BUCKET}" \
        --project="$PROJECT_ID" \
        --lifecycle-file="$lifecycle_file"
    rm -f "$lifecycle_file"

    step 'Check'
    info 'Confirm the "Cloud Run Job Failure" alert policy matches every job, including advance-dispatch:'
    info "  gcloud alpha monitoring policies list --project=${PROJECT_ID} --format='value(displayName,conditions[0].conditionMatchedLog.filter)'"
}

# ---------------------------------------------------------------- #
# Deploy
# ---------------------------------------------------------------- #

do_deploy() {
    local python_path='.venv/bin/python'
    [[ -x "$python_path" ]] || die 'no .venv/bin/python; create the venv first (see README.md)'

    if [[ "$RUN_TESTS" == true ]]; then
        step 'Tests'
        "$python_path" -m pytest -q || die 'tests failed: nothing deployed. Use --skip-tests to override.'
    else
        warn 'Skipping tests.'
    fi

    step 'Validate templates'
    "$python_path" -m dispatch.publish_templates --dry-run || die 'templates failed to validate or render'

    step 'Build and push'

    # A second, immutable tag naming the commit the image was built from
    local git_sha
    git_sha="$(git rev-parse --short HEAD 2>/dev/null || echo 'nogit')"
    if [[ -n "$(git status --porcelain 2>/dev/null)" ]]; then
        git_sha="${git_sha}-dirty"
        warn 'Working tree has uncommitted changes; the image is tagged -dirty.'
    fi
    local build_tag
    build_tag="${git_sha}-$(date -u +%Y%m%dT%H%M%SZ)"
    info "Tagging as: ${build_tag} and latest"

    run gcloud builds submit \
        --project="$PROJECT_ID" \
        --region="$REGION" \
        --tag="${IMAGE_PATH}:${build_tag}" \
        .

    # Move latest onto the new build
    run gcloud artifacts docker tags add \
        "${IMAGE_PATH}:${build_tag}" "$LATEST_IMAGE" \
        --project="$PROJECT_ID" \
        --quiet

    step 'Point the job at latest'
    if gcloud run jobs describe "$JOB_NAME" --project="$PROJECT_ID" --region="$REGION" >/dev/null 2>&1; then
        run gcloud run jobs update "$JOB_NAME" \
            --project="$PROJECT_ID" \
            --region="$REGION" \
            --image="$LATEST_IMAGE" \
            --quiet
    else
        warn "${JOB_NAME} does not exist yet. Run 'deploy/deploy.sh setup' to create it."
    fi

    step 'Publish templates'
    run "$python_path" -m dispatch.publish_templates

    step 'Done'
    info "Deployed: ${build_tag}"
}

# ---------------------------------------------------------------- #
# Main
# ---------------------------------------------------------------- #

if [[ "$COMMAND" == 'setup' ]]; then
    do_setup
else
    do_deploy
fi
