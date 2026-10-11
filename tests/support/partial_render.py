"""
Render one built section's partial on its own, as the layout would render it inside an email.
"""

import os

from dispatch.render.layout import EMAIL_MODE, RenderedImage, RenderedSection, build_environment, image_source


# ---------------------------------------------------------------- #
# Constants
# ---------------------------------------------------------------- #

# The section id the partial is rendered under, which names its images' Content-IDs
PARTIAL_SECTION_ID = 'section'

# A layout that is never rendered, since only the partial is asked for
UNUSED_LAYOUT_TEXT = ''


# ---------------------------------------------------------------- #
# Rendering
# ---------------------------------------------------------------- #

def rendered_images(result, section_id):
    """The section's images as its partial sees them in email, by image name."""
    images = {}
    for image in result.images:
        content_id = image.content_id(section_id)
        images[image.name] = RenderedImage(
            src=image_source(image, content_id, EMAIL_MODE),
            width=image.display_width,
            height=image.display_height,
            alt=image.alt,
            content_id=content_id,
        )
    return images


def render_partial(section_module, result, section_id=PARTIAL_SECTION_ID):
    """Render a section module's partial over one built SectionResult and return the HTML."""
    section = RenderedSection(
        id=section_id,
        type=section_module.TYPE_NAME,
        partial=section_module.PARTIAL,
        variables=result.variables,
        images=rendered_images(result, section_id),
        notes=result.notes,
    )

    # The partial is found beside its section module, as a real render finds it
    module_directory = os.path.dirname(os.path.abspath(section_module.__file__))
    environment = build_environment(UNUSED_LAYOUT_TEXT, [module_directory])
    partial = environment.get_template(section_module.PARTIAL)
    return partial.render(section=section)
