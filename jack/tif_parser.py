import json
import logging
import os
from typing import Dict

import numpy as np
import rasterio
import xarray as xr
from xarray import DataArray

from jack.utils import check_metadata

log = logging.getLogger(__name__)


def check_tif_metadata(metadata):
    metadata_angles = (
        metadata.get("properties", {})
        .get("acquisitionInformation", [{}])[0]
        .get("acquisitionParameters", {})
        .get("acquisitionAngles", {})
    )
    regex_checks_angles = {
        "illuminationAzimuthAngle": r"-?(?:\d+(?:\.\d+)?|\.\d+)",
        "illuminationZenithAngle": r"-?(?:\d+(?:\.\d+)?|\.\d+)",
        "instrumentAzimuthAngle": r"-?(?:\d+(?:\.\d+)?|\.\d+)",
        "instrumentZenithAngle": r"-?(?:\d+(?:\.\d+)?|\.\d+)",
    }
    numeric_checks_angles = {  # TODO: check these with Lisa
        "illuminationAzimuthAngle": [0, 180],
        "illuminationZenithAngle": [-90, 90],
        "instrumentAzimuthAngle": [0, 180],
        "instrumentZenithAngle": [-90, 90],
    }
    check_metadata(
        metadata_angles,
        regex_checks=regex_checks_angles,
        numeric_checks=numeric_checks_angles,
    )

    metadata_acquisition_parameters = (
        metadata.get("properties", {})
        .get("acquisitionInformation", [{}])[0]
        .get("acquisitionParameters", {})
    )
    regex_checks_acquisition = {
        "operationalMode": r"\d+",
    }
    check_metadata(
        metadata_acquisition_parameters, regex_checks=regex_checks_acquisition
    )

    additional_attributes = metadata["properties"]["additionalAttributes"]
    regex_checks_table = {
        "spectralTable": r"(([A-Z|\d|\d+\.\d]+,){6}[A-Z|\d|\d+\.\d]+\n)+"
    }
    check_metadata(additional_attributes, regex_checks=regex_checks_table)


def parse_tif(
    tif_path: str,
) -> tuple[Dict[str, str], DataArray, str, str]:
    """
    Parse a TIF file into data and a metadata dictionary.
    """

    # check file existence & readability
    if not os.path.isfile(tif_path):
        log.error("Image not found: %s", tif_path)
        raise FileNotFoundError(f"TIF file not found: {tif_path}")
    if not os.access(tif_path, os.R_OK):
        log.error("Image not readable: %s", tif_path)
        raise PermissionError(f"Cannot read file: {tif_path}")

    log.info("Parsing TIF: %s", tif_path)

    with rasterio.open(tif_path, "r") as f:
        data = f.read()
        headers = f.tags()
        crs = f.crs
        transform = f.transform

    log.info("image parsed: %d top-level keys", len(headers))

    try:
        metadata = json.loads(headers["GEO_METADATA"])
    except KeyError as exc:
        error_message = "TIF is missing GEO_METADATA"
        logging.error(error_message)
        raise ValueError(error_message) from exc
    except json.JSONDecodeError as exc:
        error_message = "Invalid GEO_METADATA JSON"
        logging.error(error_message)
        raise ValueError(error_message) from exc
    check_tif_metadata(metadata)

    bands, height, width = data.shape

    coordinates = {
        "band": np.arange(1, bands + 1),
        "y": np.arange(1, height + 1),
        "x": np.arange(1, width + 1),
    }

    data_array = xr.DataArray(
        data,
        dims=("band", "y", "x"),
        coords=coordinates,
    )

    for header_name in headers:
        if not header_name == "GEO_METADATA":
            data_array.attrs[header_name] = headers[header_name]

    if crs:
        data_array.attrs["spatial_ref"] = crs.to_string()

    data_array.attrs["GeoTransform"] = ",".join(map(str, transform.to_gdal()))

    return metadata, data_array, crs, transform
