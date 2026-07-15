import ast
import json
import logging
import os
import re
import shutil
import sys
import time
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from random import randint

import numpy as np
import rasterio
from rasterio import Env
#from rio_cogeo import cog_profiles, cog_translate

#from eof_eos.utils import add_geojson
#from masks.cloud import create_cloud_mask
#from masks.no_data import create_no_data_mask
#from masks.saturation import create_saturation_mask
#from transformation.geo import geo_bbox_wgs84_from_da


class CtxLogger(logging.LoggerAdapter):
    """Attach context (site/image) to log messages."""

    def process(self, msg, kwargs):
        site = self.extra.get("site")
        img = self.extra.get("image")
        prefix = ""
        if site or img:
            parts = []
            if site:
                parts.append(f"site={site}")
            if img:
                parts.append(f"image={img}")
            prefix = "[" + " ".join(parts) + "] "
        return prefix + msg, kwargs


def current_timestamp():
    """Returns the current timestamp formatted as %Y%m%dT%H%M%SZ"""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def setup_logging(
    file_name: str,
    verbosity: int,
    quiet: bool,
    log_dir: str,
    level_override: str | None,
) -> Path:
    """
    Configure console + rotating-file logging with UTC ISO-8601 timestamps.
    Returns path to the run log file.
    """
    # Decide level
    if level_override:
        level = getattr(logging, level_override)
    else:
        if quiet:
            level = logging.ERROR
        elif verbosity >= 3:
            level = logging.DEBUG
        elif verbosity == 2:
            level = logging.INFO
        elif verbosity == 1:
            level = logging.WARNING
        else:
            level = logging.ERROR

    # Root logger baseline
    root = logging.getLogger()
    root.setLevel(level)

    # Remove default handlers set by basicConfig (if any)
    for h in list(root.handlers):
        root.removeHandler(h)

    # Shared formatter: 2025-01-31T12:34:56Z INFO tardis: message
    fmt = logging.Formatter(
        fmt="%(asctime)sZ %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    class _UTC(logging.Formatter):
        converter = time.gmtime  # force UTC

    fmt.converter = time.gmtime

    # Console handler (stderr)
    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    # File handler (one file per run; rotate by size)
    log_folder_path = Path(log_dir)
    log_folder_path.resolve()
    log_folder_path.mkdir(parents=True, exist_ok=True)
    run_stamp = current_timestamp()
    unique_id = randint(
        0, 256
    )  # string to add to end of file just in case two instances start simultaneously
    log_path = log_folder_path / f"{file_name}_{run_stamp}_{unique_id:0x}.log"

    fh = RotatingFileHandler(
        log_path, maxBytes=5_000_000, backupCount=5, encoding="utf-8"
    )
    fh.setLevel(level)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # third-party noise at low verbosity
    if not level_override:
        noisy = ["urllib3", "rasterio", "rio_cogeo", "eopf", "ecmwflibs"]
        for name in noisy:
            logging.getLogger(name).setLevel(
                logging.ERROR if verbosity <= 0 else logging.WARNING
            )
    return log_path


def get_list_of_files(inputs: list, file_type: str = ".tif") -> list[str]:
    """Searches for valid input files in a list of provided directories. Default file type = .tif"""
    files = []

    error_message = "%s not recognised. Ensure that path is valid"

    def process_input(i):
        if os.path.isdir(i):
            for file in os.listdir(i):
                item_path = os.path.join(i, file)
                process_input(item_path)
        elif i.lower().endswith(file_type):
            files.append(i)
        else:
            logging.error(error_message, i)

    for i in inputs:
        process_input(i)

    return files


def get_version(root: str, suffix: str, output_folder=".") -> str:
    """Increments version to the next available number"""
    version = 1
    while True:
        padded_number = f"{version:0>4}"

        file = os.path.join(output_folder, f"{root}_{padded_number}{suffix}")
        if os.path.exists(file):
            version += 1
        else:
            return padded_number


def check_metadata(
    metadata: dict,
    regex_checks: dict = None,
    list_checks: dict = None,
    numeric_checks: dict = None,
    datetime_string_checks: dict = None,
) -> None:
    """Checks provided metadata against a list of expected formats and raises errors if inputs are missing or
    in an incorrect format"""

    if datetime_string_checks is None:
        datetime_string_checks = {}
    if numeric_checks is None:
        numeric_checks = {}
    if list_checks is None:
        list_checks = {}
    if regex_checks is None:
        regex_checks = {}
    missing_values = set()
    invalid_values = set()

    logging.info("Checking metadata")
    for key in regex_checks.keys():
        logging.debug(key)
        try:
            metadata[key]
        except KeyError:
            missing_values.add(key)
        try:
            if not re.match(f"^{regex_checks[key]}$", str(metadata[key])):
                invalid_values.add(key)
        except (ValueError, KeyError):
            invalid_values.add(key)

    for key in list_checks.keys():
        logging.debug(key)
        try:
            metadata[key]
        except KeyError:
            missing_values.add(key)

        var_type = list_checks[key]
        try:
            if not all([isinstance(x, var_type) for x in metadata[key]]):
                invalid_values.add(key)

        except (ValueError, KeyError):
            invalid_values.add(key)

    for key in numeric_checks.keys():
        logging.debug(key)
        try:
            metadata[key]
        except KeyError:
            missing_values.add(key)

        min_value, max_value = numeric_checks[key]
        value = metadata[key]
        try:
            if (
                (type(value) is not str)
                and (float(value) != value)
                and (int(value) != value)
            ):
                invalid_values.add(key)
                break
            value = float(value)
            if not min_value <= value <= max_value:
                invalid_values.add(key)

        except (ValueError, KeyError):
            invalid_values.add(key)

    for key in datetime_string_checks.keys():
        logging.debug(key)
        try:
            metadata[key]
        except KeyError:
            missing_values.add(key)

        try:
            datetime.strptime(metadata[key], datetime_string_checks[key])
        except (ValueError, KeyError):
            invalid_values.add(key)

    if missing_values:
        error_message = f"Missing metadata entries identified: {missing_values}"
        logging.error(error_message)
        raise Exception(error_message)
    if invalid_values:
        error_message = f"Invalid metadata identified: {invalid_values}"
        logging.error(error_message)
        raise Exception(error_message)


def ensure_file(p: Path, what: str) -> None:
    if not p.exists():
        logging.error("Missing %s: %s", what, p)
        sys.exit(2)


def copy_logs(log_folder: Path, output_folder: Path):
    logging.info(f"Copying logs from {log_folder} to {output_folder}")

    shutil.copytree(
        log_folder, f"{output_folder}/{log_folder.name}", dirs_exist_ok=True
    )


def cleanup_intermediates(outs: dict[str, Path], logger: logging.LoggerAdapter) -> None:
    """
    Delete intermediate files:
      - cog/*.tif
    We delete only the contents (not the parent directories).
    """
    root = outs.get("root")
    if root is None:
        logger.info("No root folder configured for cleanup")
        return

    folder = Path(root)

    logging.info(f"Deleting folder {folder}")
    try:
        shutil.rmtree(folder)
    except FileNotFoundError:
        logging.info("Folder already removed: %s", folder)
    except Exception:
        logging.exception("Unable to delete folder %s", folder)
    else:
        logging.info("Folder deleted: %s", folder)


def generate_outputs(
    da,
    cog_path,
    transform,
    crs,
    quality_path,
    wavelengths,
    name_root,
    metadata=None,
    raw_metadata=None,
):

    try:
        mask_debug = ((~np.isfinite(da.values)) | (da.values <= 0)).astype(np.uint8)
        logging.info(
            "transform: pre-write no-data samples=%d total_samples=%d no_data_pct=%.1f",
            int(np.count_nonzero(mask_debug)),
            int(mask_debug.size),
            (
                (np.count_nonzero(mask_debug) / mask_debug.size) * 100
                if mask_debug.size
                else 0.0
            ),
        )
        out = write_cog(
            da,
            metadata=metadata,
            raw_metadata=raw_metadata,
            cog_path=cog_path,
            transform=transform,
            wavelengths=wavelengths,
            crs=crs,
            profile_name="deflate",
        )
        create_cloud_mask(
            data_array=da.copy(deep=True),
            quality_path=quality_path,
            mask_root=name_root,
        )
        create_no_data_mask(
            data_array=da, quality_path=quality_path, mask_root=name_root
        )
        create_saturation_mask(
            data_array=da,
            quality_path=quality_path,
            mask_root=name_root,
            transform=transform,
            crs=crs,
        )
        logging.info(
            "to_cog: pre-write cube no-data samples=%d",
            int(np.count_nonzero((~np.isfinite(da.values)) | (da.values <= 0))),
        )
        logging.info("transform: wrote standard COG → %s", out)
    except Exception:
        logging.exception("transform: reader.to_cog failed for %s", cog_path)
        raise


def write_cog(
    data_array,
    raw_metadata,
    cog_path,
    transform,
    crs,
    wavelengths,
    metadata=None,
    profile_name="deflate",
    config=None,
    **kwargs,
):
    t0 = time.perf_counter()
    logging.info("to_cog_start path=%s profile=%s", cog_path, profile_name)

    # Remove added borders and other dark pixels
    data_array = data_array.where(data_array >= 0.005, None)

    tmp = cog_path + ".tmp.tif"
    profile = {
        "driver": "GTiff",
        "height": data_array.sizes["y"],
        "width": data_array.sizes["x"],
        "count": data_array.sizes["band"],
        "dtype": str(data_array.dtype),
        "nodata": 0,
    }
    logging.debug(
        "to_cog_profile height=%d width=%d bands=%d dtype=%s nodata=%s crs=%s",
        profile["height"],
        profile["width"],
        profile["count"],
        profile["dtype"],
        profile.get("nodata"),
        crs,
    )

    # Prefer the latest CRS / transform from self.da.attrs if present
    crs_for_write = crs
    transform_for_write = transform

    # if data_array is not None:
    #     gt = data_array.attrs.get("GeoTransform")
    #     if gt is not None:
    #         if isinstance(gt, str):
    #             transform_for_write = tuple(float(v) for v in gt.split(","))
    #         else:
    #             transform_for_write = tuple(float(v) for v in gt)
    #
    #     crs_attr = data_array.attrs.get("crs") or data_array.attrs.get("spatial_ref")
    #     if crs_attr:
    #         crs_for_write = crs_attr

    if crs_for_write and transform_for_write:
        profile["crs"] = crs
        profile["transform"] = transform

    with rasterio.open(tmp, "w", **profile) as dst:
        # write planes
        for i in range(data_array.sizes["band"]):
            dst.write(data_array.values[i], i + 1)

        # Embed radiometry / SMAC provenance tags.
        for key in [
            "radiometry",
            "atmospheric_correction",
            "smac_sensor_proxy",
            "smac_proxy_bands",
            "smac_water_vapour",
            "smac_ozone",
            "smac_pressure",
            "smac_aot_550",
        ]:
            value = data_array.attrs.get(key)
            if value is not None:
                dst.update_tags(**{key: str(value)})
        # Embed wavelengths as JSON metadata
        if wavelengths is None:
            logging.info("No associated wavelength metadata available for %s", cog_path)
        else:
            try:
                dst.update_tags(
                    wavelengths=json.dumps(
                        [float(v) for v in np.asarray(wavelengths).tolist()]
                    )
                )
            except (TypeError, ValueError) as exc:
                logging.info(
                    "Failed to write wavelength metadata for %s: %s", cog_path, exc
                )

        # Add geospatial bounds tags (if available)
        if bbox := data_array.attrs.get("bbox"):
            bbox = ast.literal_eval(bbox)
            corners = ast.literal_eval(
                data_array.attrs.get("geospatial_corners_lonlat")
            )
        else:
            bb = geo_bbox_wgs84_from_da(data_array)

            if bb is None:
                error_message = (
                    "RCIReader.to_cog: cannot compute WGS84 bbox because DataArray has no valid "
                    "CRS/GeoTransform"
                )
                logging.error(error_message)
                raise ValueError(error_message)

            bbox, corners = bb

        size = sys.getsizeof(dst)
        if not metadata:
            metadata = add_geojson(
                metadata=raw_metadata,
                bbox=bbox,
                file_name=cog_path.split("/")[-1],
                size=size,
            )

        additional_attributes = metadata.setdefault("properties", {}).setdefault(
            "additionalAttributes", {}
        )

        logging.info(
            "to_cog: GEO_METADATA geometry fields mapProjection=%s mapProjectionEpsg=%s "
            "demName=%s demSource=%s 2dName=%s 2dSource=%s",
            additional_attributes.get("mapProjection"),
            additional_attributes.get("mapProjectionEpsg"),
            additional_attributes.get("demName"),
            additional_attributes.get("demSource"),
            additional_attributes.get("2dName"),
            additional_attributes.get("2dSource"),
        )

        dst.update_tags(
            bbox=json.dumps(bbox),
            spatial_bounds=json.dumps(bbox),
            geospatial_lon_min=str(bbox[0]),
            geospatial_lat_min=str(bbox[1]),
            geospatial_lon_max=str(bbox[2]),
            geospatial_lat_max=str(bbox[3]),
            geospatial_bounds=json.dumps(bbox),
            geospatial_corners_lonlat=json.dumps(corners),
            GEO_METADATA=json.dumps(
                metadata,
                default=lambda d: {k: v for k, v in d.__dict__.items() if v},
            ),
        )

    dst_profile = cog_profiles[profile_name]

    kwargs.pop("config", None)
    gdal_cfg = config or {"GDAL_NUM_THREADS": "ALL_CPUS"}

    # Translate temporary GTiff to COG
    with Env(**gdal_cfg):
        cog_translate(
            tmp,
            cog_path,
            dst_profile,
            in_memory=False,
            quiet=True,
            **kwargs,
        )
    logging.info(
        "to_cog_done path=%s bands=%d size=%dx%d dtype=%s dur=%.2fs",
        cog_path,
        data_array.sizes["band"],
        data_array.sizes["x"],
        data_array.sizes["y"],
        data_array.dtype,
        time.perf_counter() - t0,
    )

    os.remove(tmp)
    return cog_path


def rewrite_cog(
    data_array,
    metadata,
    cog_path,
    transform,
    crs,
    wavelengths,
    profile_name="deflate",
    config=None,
    **kwargs,
):
    t0 = time.perf_counter()
    logging.info("to_cog_start path=%s profile=%s", cog_path, profile_name)

    # Remove added borders and other dark pixels
    data_array = data_array.where(data_array >= 0.005, None)

    tmp = cog_path + ".tmp.tif"
    profile = {
        "driver": "GTiff",
        "height": data_array.sizes["y"],
        "width": data_array.sizes["x"],
        "count": data_array.sizes["band"],
        "dtype": str(data_array.dtype),
        "nodata": 0,
    }
    logging.debug(
        "to_cog_profile height=%d width=%d bands=%d dtype=%s nodata=%s crs=%s",
        profile["height"],
        profile["width"],
        profile["count"],
        profile["dtype"],
        profile.get("nodata"),
        crs,
    )

    # Prefer the latest CRS / transform from self.da.attrs if present
    crs_for_write = crs
    transform_for_write = transform

    if crs_for_write and transform_for_write:
        profile["crs"] = crs
        profile["transform"] = transform

    with rasterio.open(tmp, "w", **profile) as dst:
        # write planes
        for i in range(data_array.sizes["band"]):
            dst.write(data_array.values[i], i + 1)

        # Embed radiometry / SMAC provenance tags.
        for key in [
            "radiometry",
            "atmospheric_correction",
            "smac_sensor_proxy",
            "smac_proxy_bands",
            "smac_water_vapour",
            "smac_ozone",
            "smac_pressure",
            "smac_aot_550",
        ]:
            value = data_array.attrs.get(key)
            if value is not None:
                dst.update_tags(**{key: str(value)})
        # Embed wavelengths as JSON metadata
        if wavelengths is None:
            logging.info("No associated wavelength metadata available for %s", cog_path)
        else:
            try:
                dst.update_tags(
                    wavelengths=json.dumps(
                        [float(v) for v in np.asarray(wavelengths).tolist()]
                    )
                )
            except (TypeError, ValueError) as exc:
                logging.info(
                    "Failed to write wavelength metadata for %s: %s", cog_path, exc
                )

        # Add geospatial bounds tags (if available)
        bb = geo_bbox_wgs84_from_da(data_array)

        if bb is None:
            error_message = (
                "RCIReader.to_cog: cannot compute WGS84 bbox because DataArray has no "
                "valid CRS/GeoTransform"
            )
            logging.error(error_message)
            raise ValueError(error_message)

        bbox, corners = bb

        size = sys.getsizeof(dst)
        metadata = add_geojson(
            metadata=metadata,
            bbox=bbox,
            file_name=cog_path.split("/")[-1],
            size=size,
        )

        additional_attributes = metadata.setdefault("properties", {}).setdefault(
            "additionalAttributes", {}
        )

        logging.info(
            "to_cog: GEO_METADATA geometry fields mapProjection=%s mapProjectionEpsg=%s "
            "demName=%s demSource=%s 2dName=%s 2dSource=%s",
            additional_attributes.get("mapProjection"),
            additional_attributes.get("mapProjectionEpsg"),
            additional_attributes.get("demName"),
            additional_attributes.get("demSource"),
            additional_attributes.get("2dName"),
            additional_attributes.get("2dSource"),
        )

        dst.update_tags(
            bbox=json.dumps(bbox),
            spatial_bounds=json.dumps(bbox),
            geospatial_lon_min=str(bbox[0]),
            geospatial_lat_min=str(bbox[1]),
            geospatial_lon_max=str(bbox[2]),
            geospatial_lat_max=str(bbox[3]),
            geospatial_bounds=json.dumps(bbox),
            geospatial_corners_lonlat=json.dumps(corners),
            GEO_METADATA=json.dumps(
                metadata,
                default=lambda d: {k: v for k, v in d.__dict__.items() if v},
            ),
        )

    dst_profile = cog_profiles[profile_name]

    kwargs.pop("config", None)
    gdal_cfg = config or {"GDAL_NUM_THREADS": "ALL_CPUS"}

    # Translate temporary GTiff to COG
    with Env(**gdal_cfg):
        cog_translate(
            tmp,
            cog_path,
            dst_profile,
            in_memory=False,
            quiet=True,
            **kwargs,
        )
    logging.info(
        "to_cog_done path=%s bands=%d size=%dx%d dtype=%s dur=%.2fs",
        cog_path,
        data_array.sizes["band"],
        data_array.sizes["x"],
        data_array.sizes["y"],
        data_array.dtype,
        time.perf_counter() - t0,
    )

    os.remove(tmp)
    return cog_path
