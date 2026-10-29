"""The picture shown for a scheduled task, made from an image a run reports."""

import io

from PIL import Image

TASK_IMAGE_MAX_SIDE = 640
TASK_IMAGE_MIME = "image/webp"


def task_image_thumbnail(data: bytes) -> bytes:
    """A WebP no larger than TASK_IMAGE_MAX_SIDE on either side. Raises on
    bytes Pillow cannot read."""
    with Image.open(io.BytesIO(data)) as image:
        image.seek(0)
        image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
        image.thumbnail((TASK_IMAGE_MAX_SIDE, TASK_IMAGE_MAX_SIDE))
        out = io.BytesIO()
        image.save(out, format="WEBP", quality=85)
        return out.getvalue()
