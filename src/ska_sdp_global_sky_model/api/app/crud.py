"""
CRUD functionality goes here.
"""

import logging

from astropy.coordinates import SkyCoord
from healpix_alchemy import Tile
from sqlalchemy import and_
from sqlalchemy.orm import Session

from ska_sdp_global_sky_model.api.app.model import AOI, Source

logger = logging.getLogger(__name__)


def get_local_sky_model(
    db,
    ra: list,
    dec: list,
    _flux_wide: float,
    _telescope: str,
    _fov: float,
) -> dict:
    """
    Retrieves a local sky model (LSM) from a global sky model for a specific celestial observation.

    The LSM contains information about celestial sources within a designated region of the sky. \
        This function extracts this information from a database (`db`) based on the provided \
        right ascension (RA) and declination (Dec) coordinates.

    Args:
        db (Any): A database object containing the global sky model. The specific type of \
            database object will depend on the implementation.
        ra (list[float]): A list containing two right ascension values (in degrees) that define \
            the boundaries of the desired LSM region.
        dec (list[float]): A list containing two declination values (in degrees) that define the \
            boundaries of the desired LSM region.
        _flux_wide (float): Placeholder for future implementation of wide-field flux \
            of the observation (in Jy). Currently not used.
        _telescope (str): Placeholder for future implementation of the telescope name \
            being used for the observation. Currently not used.
        _fov (float): Placeholder for future implementation of the telescope's field of\
            view (in arcminutes). Currently not used.

    Returns:
        dict: A dictionary containing the LSM data. The structure of the dictionary is:

            {
                "region": {
                    "ra": List of RA coordinates (same as input `ra`).
                    "dec": List of Dec coordinates (same as input `dec`).
                },
                "count": Number of celestial sources found within the LSM region.
                "sources_in_area_of_interest": List of dictionaries, each representing a \
                    celestial source within the LSM region.
                    The structure of each source dictionary depends on the data model stored \
                        in the database (`db`).
            }
    """

    corners = SkyCoord(ra, dec, frame="icrs", unit="deg")
    areas_or_interest = [AOI(hpx=hpx) for hpx in Tile.tiles_from(corners)]

    # pylint: disable=expression-not-assigned
    [db.add(aoi) for aoi in areas_or_interest]
    db.commit()  # TODO: we need to clean these up later on again.    # pylint: disable=fixme

    aoi_ids = [aoi.id for aoi in areas_or_interest]
    sources_in_area_of_interest = (
        db.query(Source)
        .filter(AOI.id.in_(aoi_ids), AOI.hpx.contains(Source.Heal_Pix_Position))
        .all()
    )

    logger.info(
        "Retrieve %s point sources within the area of interest.",
        str(len(sources_in_area_of_interest)),
    )

    local_sky_model = {
        "region": {"ra": ra, "dec": dec},
        "count": len(sources_in_area_of_interest),
        "sources_in_area_of_interest": [
            source.to_json(db) for source in sources_in_area_of_interest
        ],
    }

    return local_sky_model


def get_coverage_range(ra: float, dec: float, fov: float) -> tuple[float, float, float, float]:
    """
    This function calculates the minimum and maximum RA and Dec values
    covering a circular field of view around a given source position.

    Args:
        ra: Right Ascension of the source (in arcminutes)
        dec: Declination of the source (in arcminutes)
        fov: Diameter of the field of view (in arcminutes)

    Returns:
        A tuple containing (ra_min, ra_max, dec_min, dec_max)
    """

    # Input validation
    if fov <= 0:
        raise ValueError("Field of view must be a positive value.")
    if not 0 <= ra < 360:
        raise ValueError("Right Ascension (RA) must be between 0 and 360 degrees.")
    if not -90 <= dec <= 90:
        raise ValueError("Declination (Dec) must be between -90 and 90 degrees.")

    # Convert field of view diameter to radius
    fov_radius = fov / 2.0

    # Calculate RA range (assuming circular field)
    ra_min = ra - fov_radius
    ra_max = ra + fov_radius

    # Apply wrap-around logic for RA (0 to 360 degrees)
    ra_min = ra_min % 360.0
    ra_max = ra_max % 360.0

    # Calculate Dec range (assuming small field of view, no wrap-around)
    dec_min = dec - fov_radius
    dec_max = dec + fov_radius

    return ra_min, ra_max, dec_min, dec_max


# pylint: disable=too-many-arguments


def get_sources_by_criteria(
    db: Session,
    ra: float = None,
    dec: float = None,
    flux_wide: float = None,
    telescope: str = None,
    fov: float = None,
) -> list[Source]:
    """
    This function retrieves all Source entries matching the provided criteria.

    Args:
        db: A sqlalchemy database session object
        ra: Right Ascension (optional)
        dec: Declination (optional)
        flux_wide: Wideband flux (optional)
        telescope: Telescope name (optional)
        fov: Field of view (optional)

    Returns:
        A list of Source objects matching the criteria.
    """
    query = db.query(Source)

    # Build filter conditions based on provided arguments
    filters = []
    if ra is not None:
        filters.append(Source.RAJ2000 == ra)
    if dec is not None:
        filters.append(Source.DecJ2000 == dec)
    if flux_wide is not None:
        filters.append(Source.flux_wide == flux_wide)  # Replace with actual column name
    if telescope is not None:
        filters.append(Source.telescope == telescope)
    if fov is not None:
        filters.append(Source.fov == fov)  # Replace with actual column name

    # Combine filters using 'and_' if any filters are present
    if filters:
        query = query.filter(and_(*filters))

    return query.all()
