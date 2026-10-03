# AdVance App #
I'm building an election campaign analytics platform that draws on data from Google's Ad Transparency Centre via a BigQuery query and Meta's ads_archive API, collecting the raw advert image / video / text, classifying and analysing it with the help of Vertex AI.

## Back End ##
My back end project is /Users/talisevans/Projects/Personal/adVance/AdVance-back-end

## API ##
My API project is /Users/talisevans/Projects/Personal/adVance/AdVance-api

## Front End ##
My Front End Angular app is /Users/talisevans/Projects/Personal/adVance/AdVance-dispatch/vic_election_weekly_briefing.html

# AdVance Dispatch (Dispatch) - NEW #
I'm working on a brand new feature, with my project code to be stored in /Users/talisevans/Projects/Personal/adVance/AdVance-dispatch called *Dispatch*.

At a high level, Dispatch is a tool that will enable pre-defined email templates (called **Dispatch Templates**) to be configured for a given jurisdiciton, over a given period, to send emails to a given distribution list.

As an example, let's say the Victorian State Election is coming up on 28 November 2026.  A user would be able to go to Dispatch, which will be a new side menu option in our Angular app, and configure a **Dispatch Record**, which would enable the user to effectively create a schedule that says between 1 July 2026 and 28 November 2026 I want you to send an email to a given distribution list of email addresses every {monday} at {9am - VIC time} with the template of {a given Dispatch Template from our list}

This then allows a group of people to receive that email template.

## Dispatch Template ##
Dispatch template configs will be stored in a new `dispatch_templates` Firestore collection with a data structures that looks similar to 
```
[
    {
        "id": "XXXXX",
        "name": "Weekly Campaign Brief",
        "required_properties:[
            "start_date": date,
            "end_date: date,
            "jurisdiction": {one of our defined jurisdictions - federal, state, international},
            "state": (nullable) one of our defined states
        ],
        "template_path": advance_dispatch/templates/{weekly_campaign_brief.html},
        "globals":{
            "exclusions":[
                {
                    "classification: ["government"]

                },
            ]
             "filters:[]
            ]
        },
        "sections":{
            "top_10_seats_by_spend":{
                "exclusions":[],
                "filters:[
                    "classification": ["political participant"]
                ]
            },
            "messaging_tone":{
                "exclusions":[],
                "filters:[
                    "affiliation": ["aff_labor","aff_liberal","aff_greens","aff_climate_200"]
                ]
            }
        }
    }
]
```

Essentially, this document in our dispatch_templates Firestore collection captures the properties of the email template that are needed.  Think of this like a class / interface that defines the propeties that are required.

Using the example above, the `required_properties` tells us that we need a start_date, end_date, jurisdiction, state ad properties to collect from the user when they are provisioning a new 'Dispatch Record'.

### HTML Template ###
The `template_path` is a path reference to a bucket `advance_dispatch/templates` that has all of the HTML templates linked to each Dispatch Template.  This is essentially the HTML template file that our script will use at runtime to build the HTML email that gets distributed.

Adding Dispatch Templates is a job for a developer, there is no interface in Angualar that allows users to perform CRUD operations on Dispatch Templates. 

We should try to store as many of the rules / logic in a structured way in this Dispatch Template JSON as possible.  That way, our code can be light, and reusable across a number of Dispatch Templates, rather than creating lots of helper functions in /src/ in our project that ultimately duplicate functionality across multiple Dispatch Templates that only need the information cut in a slightly different way that a parameter in the JSON payload could have handled. 

## Dispatch Recorrd ##
A dispatch record will be stored in a new `dispatch_records` firestore collection with a data structure that looks slimiar to 
```
[
    {
        "id": "XXXXX",
        "template_id": "XXXXXXX"
        "required_property_values:[
            "start_date": "2026-07-01",
            "end_date: "2026-11-28,
            "jurisdiction": "state",
            "state": "VIC"
        ],
        "recipient_list": [
            "talis.evans@gmail.com",
            "james@stvns.com"
        ],
        "cron: "0 9 * * *",
        "timezone: "{an appropriate timezone format}",
        "start_delivery": "2026-10-01"
        "end_delivery": "2026-11-28",
        "status" "active" (or inactive, if toggle paused)
    }
]
```

Users are able to perform CRUD operations on Dispatch Records through our Angular interface.  There's a new setting  in our sidebar "Dispatch" that lists two tabs - current Dispatch Records and "Expired".  When a user toggles to "Expired" they see all dispatch records that have an `end_delivery` in the past.  "Active" shows all Dispatch Records with an `end_delivery` in the future OR the current date.  

When a user creates a new or edits an existing Dispatch Record, a side pane slides in, much like our Creator Mapping settings.  That side pane gives the user the ability to edit or add required property values - which dynamically populate based on the `required_properties` of the Dispatch Template, add recipient emails, set the crontab schedule and timezone, and start and end delivery times.  Optionally, the user can toggle a 'status' to either 'active' or 'inactive'.

While we store this delivery schedule in 'cron' format, in reality `daily` updates will be the most refrequent.  I don't want to create schedules for CloudRun jobs to run every minutes / hour, etc when in reality there will only ever be 1 or 2 active Dispatch Records, and at most they'll be sent daily.  We need a smart way to only run the CloudRun job when we actually have a schedule that needs it - rather than having all of these redundant CloudRun jobs executing unnecessarily all the time.

Only admin users in AdVance (reading their Firestore allowlist record) get to see thsi Dispatch feature - the same as the settings features.

# Dispatch Script #
In /Users/talisevans/Projects/Personal/adVance/AdVance-dispatch we will create a new script that is invoked at runtime to generate a Dispatch (html email going to the `recipient_list`).  It will:
    - query our gold layer data to get the information it needs, 
    - read whatever properties / logic exists in the `dispatch_template` json, 
    - get the HTML template from the bucket
    - work through processing logic to build our Dispatch from the data it's collected
    - send the compiled HTML email template to the recipient list for the Dispatch Record it's processing 

The architecture of our script should be modular.  We should consider creating each 'section' of a Dispatch Template as a reusable block of code, which means multiple Dispatch Templates could share "sections" if that's how the email report gets built.

# Weekly Campaign Brief #
We'll have a number of Dispatch Templates loaded into the system over time.  But, to start with, we already have one we can add, which is a "Weekly Election Campaign Brief".  The HTML file for this Campaign Brief is /Users/talisevans/Projects/Personal/adVance/AdVance-dispatch/vic_election_weekly_briefing.html.  This HTML file embeds the raw data in line, so we'll need to extract the raw data to turn the HTML document into a true 'template' form but it gives us a good starting point.

You can see from how I've suggested a Dispatch Template could look. We have a `global` exclusion for "classification: ["government"].  This means that the government classification on adverts (content creators) is excluded from the Dispatch Template all together.

Where we also have a `section` area.  the `section` area refers to individual blocks within the Dispatch Template.  In this example, we're filtering the `top_10_seats_by_spend` section to only include political participants.  So, all other participants (excluding government at the global level) are included in our Dispatch for all other sections in our report, BUT for the top 10 seats by spend section, we filter to only include Political Participants.  

Key facts about this template are:

## Statewide Spend ##
This quotes biases that don't exist - Centre Left / Centre Right don't exist.  We should use the actual biases that are in our data structure.  For Content Creators that don't have a mapped affiliation (with an associated bias), we add them as an 'unmapped' bias, sitting in the midpoint of that half doughnut chart.

## Cumulative Spend ##
Let's split this cumulative chart into two columns.  The left column shows all 'biases', the right colunn shows all 'affiliations', including 'unmapped' affiliations.

## Messaging & Tone ###
generates a card for each affiliation in the filtered affiliations list for that section

# Top 10 seats by spend"
Filters by political participant classification, and reprots the `affiliation` with the leading 7 day and 28 day spend, including the 2nd biggest spender.  This 7 day and 28 day spend are calculated from the date the script runs
