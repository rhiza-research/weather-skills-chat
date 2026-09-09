"""Unauthenticated route that serves an artifact for a one-time handoff nonce.

The nonce in the URL is the credential, and it is deleted when redeemed. Unknown, expired, and
already-used nonces all return the same 404.
"""

import logging

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from open_webui.utils.artifact_handoff import redeem
from open_webui.utils.artifacts import resolve_in_sandbox

log = logging.getLogger(__name__)

router = APIRouter()

NOT_FOUND_DETAIL = "That link is not valid."


@router.get("/{nonce}")
async def serve_handoff(nonce: str):
    """Serve the artifact for this nonce as an attachment.

    No authentication dependency. The nonce is deleted before the file is read, so a second request
    returns 404 even if the first has not finished.
    """
    claimed = redeem(nonce)
    if claimed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL
        )

    session_id, relpath = claimed
    try:
        target = resolve_in_sandbox(session_id, relpath)
    except Exception:
        # The path was stored when the link was minted, so this means the session or file changed.
        log.exception("A redeemed handoff could not be resolved")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL
        )
    if not target.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL
        )

    return FileResponse(
        target, filename=target.name, content_disposition_type="attachment"
    )
