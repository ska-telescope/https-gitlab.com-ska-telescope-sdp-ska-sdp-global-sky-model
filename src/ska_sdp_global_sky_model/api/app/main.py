# pylint: disable=no-member
"""
A simple fastAPI to obtain a local sky model from a global sky model.
"""

# pylint: disable=too-many-arguments, broad-exception-caught
# pylint: disable=too-many-positional-arguments
import logging
import os
import tempfile
from typing import Optional

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.middleware.cors import CORSMiddleware

from ska_sdp_global_sky_model.api.app.crud import get_local_sky_model
from ska_sdp_global_sky_model.api.app.ingest import get_full_catalog
from ska_sdp_global_sky_model.configuration.config import MWA, RACS, RCAL, DataStore, get_ds

logger = logging.getLogger(__name__)

app = FastAPI()
app.add_middleware(GZipMiddleware, minimum_size=1000)

origins = []

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/ping", summary="Ping the API")
def ping():
    """Returns {"ping": "live"} when called"""
    logger.debug("Ping: alive")
    return {"ping": "live"}


def ingest(ds: DataStore, catalog_config: dict):
    """Ingest catalog"""
    try:
        if get_full_catalog(ds, catalog_config):
            return True
        logger.error("Error ingesting the catalogue")
        return False
    except Exception as e:  # pylint: disable=broad-exception-caught
        raise e


@app.get("/ingest-gleam-catalog", summary="Ingest GLEAM {used in development}")
def ingest_gleam(ds: DataStore = Depends(get_ds)):
    """Ingesting the Gleam catalogue"""
    logger.info("Ingesting the Gleam catalogue...")
    return ingest(ds, MWA)


@app.get("/ingest-racs-catalog", summary="Ingest RACS {used in development}")
def ingest_racs(ds: DataStore = Depends(get_ds)):
    """Ingesting the RACS catalogue"""
    logger.info("Ingesting the RACS catalogue...")
    return ingest(ds, RACS)


@app.get("/sources", summary="See all the point sources")
def get_point_sources(ds: DataStore = Depends(get_ds)):
    """Retrieve all point sources"""
    logger.info("Retrieving all point sources...")
    sources = ds.all()
    return sources.write_json()


@app.get("/local_sky_model", response_class=StreamingResponse)
async def get_local_sky_model_endpoint(
    request: Request,
    ra: str,
    dec: str,
    telescope: str,
    fov: float,
    ds: DataStore = Depends(get_ds),
):
    """
    Get the local sky model from a global sky model.

    Args:
        ra (float): Right ascension of the observation point in degrees.
        dec (float): Declination of the observation point in degrees.
        flux_wide (float): Wide-field flux of the observation in Jy.
        telescope (str): Name of the telescope being used for the observation.
        fov (float): Field of view of the telescope in arcminutes.
        ds (DataStore):

    Returns:
        dict: A dictionary containing the local sky model information.

        The dictionary includes the following keys:
            - request: Allow users to free-form use search criteria
            - ra: The right ascension provided as input.
            - dec: The declination provided as input.
            - telescope: The telescope name provided as input.
            - fov: The field of view provided as input.
            - ds: ......
    """
    advanced_search = {}
    for key, value in request.query_params.items():
        if key in ["ra", "dec", "fov", "telescope"]:
            continue
        advanced_search[key] = value
    logger.info(
        "Requesting local sky model with the following parameters: ra:%s, \
dec:%s, flux_wide:%s, telescope:%s, fov:%s",
        ra,
        dec,
        telescope,
        fov,
        advanced_search,
    )
    local_model = get_local_sky_model(
        ds, ra.split(";"), dec.split(";"), telescope, fov, advanced_search
    )
    return StreamingResponse(local_model.stream(), media_type="text/event-stream")


@app.post("/upload-rcal", summary="Ingest RCAL from a CSV {used in development}")
async def upload_rcal(
    file: UploadFile = File(...), ds: DataStore = Depends(get_ds), config: Optional[dict] = None
):
    """
    Uploads and processes an RCAL catalog file. This is a development endpoint.
    The file is expected to be a CSV file as exported from the GLEAM catalog.
    There is an example in the `tests/data` directory of this package.

    Parameters:
        file (UploadFile): The RCAL file to upload.

    Raises:
        HTTPException: If the file type is invalid or there is an error with the
        database session or disk space.

    Returns:
        JSONResponse: A success message if the RCAL file is uploaded and ingested successfully,
        or an error message if there is an issue with the catalog ingest.
    """
    try:
        if file.content_type != "text/csv":
            raise HTTPException(
                status_code=400, detail="Invalid file type. Please upload a CSV file."
            )

        # Check if there is sufficient disk space to write the file
        statvfs = os.statvfs("/")
        free_space = statvfs.f_frsize * statvfs.f_bavail

        # Create a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as temp_file:
            temp_file_path = temp_file.name

            # Write the uploaded file to the temporary file
            contents = await file.read()
            file_size = len(contents)
            if file_size > free_space:
                raise HTTPException(status_code=400, detail="Insufficient disk space.")

            temp_file.write(contents)
            temp_file.flush()
            temp_file.close()
            # Process the CSV data (example: print the path of the temporary file)
            logger.info("Temporary file created at: %s, size: %d", temp_file_path, file_size)
            rcal_config = config
            if not rcal_config:
                rcal_config = RCAL.copy()

            rcal_config["ingest"]["file_location"][0]["key"] = temp_file_path
            logger.info("Ingesting the catalogue...")

            if ingest(ds, rcal_config):
                return JSONResponse(
                    content={"message": "RCAL uploaded and ingested successfully"},
                    status_code=200,
                )

            os.remove(temp_file_path)

            return JSONResponse(
                content={"message": "Error ingesting the catalogue (already present?)"},
                status_code=500,
            )
    except Exception as e:
        logger.error("Error on RCAL catalog ingest: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e
