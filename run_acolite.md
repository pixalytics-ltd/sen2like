---
jupyter:
  jupytext:
    formats: ipynb,md
    text_representation:
      extension: .md
      format_name: markdown
      format_version: '1.3'
      jupytext_version: 1.17.3
  kernelspec:
    display_name: acolite
    language: python
    name: python3
---

```python
import os
import sys
import shutil
import glob
import numpy as np
from osgeo import gdal, ogr, osr
import argparse
import subprocess
import zipfile
import csv
import datetime
import logging

log = logging.getLogger(__name__)

# Setup ICOR environment
icorpath = "/opt/vito/icor"
icor = os.path.join(icorpath, "src/icor.py")
os.environ["ICOR_DIR"] = icorpath

# Check what machine is being used
homedir = os.path.expanduser('~')
from sys import platform
if platform == "win32":
    apath = r"{}\Documents\GitHub\acolite".format(homedir)
    acenv = r"{}\Anaconda3\envs\acolite".format(homedir)
    penv = r"{}\Anaconda3\envs\plastics_env".format(homedir)

    # Setup GDAL paths
    os.environ['PROJ_LIB'] = os.path.join(acenv,r"Library\share\proj")
    os.environ['GDAL_DATA'] = os.path.join(acenv,r"Library\share")
    
    # Setup python access
    python3 = os.path.join(penv,r"bin\python3")

elif "jovyan" in homedir: 
    apath = r"{}/notebooks/UNEP-Plastic-Detection/src/acolite".format(homedir)
    acenv = r"/opt/conda/envs/acolite"
    
    # Setup GDAL paths
    os.environ['PROJ_LIB'] = os.path.join(acenv,r"Library/share/proj")
    os.environ['GDAL_DATA'] = os.path.join(acenv,r"Library/share")

    # Setup python access
    python3ac = os.path.join(acenv,r"bin/python3")
else:
    apath = r"../src/acolite"
    acenv = r"{}/anaconda3/envs/acolite".format(homedir)
    penv = r"{}/anaconda3/envs/icor_env".format(homedir)
    polyenv = r"{}/anaconda3/envs/polymer_env".format(homedir)
    polypath = r"{}/notebooks/src/polymer".format(homedir)
    
    # Setup GDAL paths
    os.environ['PROJ_LIB'] = os.path.join(acenv,r"Library/share/proj")
    os.environ['GDAL_DATA'] = os.path.join(acenv,r"Library/share")

    # Setup python access
    python3 = os.path.join(penv,r"bin/python3")
    python3ac = os.path.join(acenv,r"bin/python3")

# add acolite clone to Python path and import acolite
print("Acolite path: {}".format(apath))
sys.path.append(apath)
import acolite as ac

# add jack functions
from jack.tif_parser import parse_tif
```

```python
# Run acolite for each file
def run_acolite(l1files, outdir, verbose = False):
    
    # create empty dict and set some settings
    settings = {}
    # set settings provided above
    settings['limit'] = None # No bouding box subsetting
    settings['output'] = outdir
    if verbose:
        # verbosity - full is 5
        settings['verbosity'] = 2
    # Output Rayleigh corrected
    settings['output_rhorc'] = False
    # Compress NetCDF
    settings['l2r_nc_compression'] = False
    # Single AOT for the scene
    settings['dsf_aot_estimate'] = 'fixed'

    # CHRIS specific setting
    settings['chris_noise_reduction'] = False
    settings['chris_interband_calibration'] = False

    # process the current bundle
    settings['inputfile'] = l1files
    ac.acolite.acolite_run(settings=settings)

```

```python
def setup_settings(l1files,outdir, verbose=False):
    # create empty dict and set some settings
    settings = {}
    # set settings provided above
    settings['limit'] = None # No bouding box subsetting
    settings['output'] = outdir
    if verbose:
        # verbosity - full is 5
        settings['verbosity'] = 2
    # Output Rayleigh corrected
    settings['output_rhorc'] = False
    # Compress NetCDF
    settings['l2r_nc_compression'] = False
    # Output GeoTiFF
    settings['l2r_export_geotiff'] = True
    # Single AOT for the scene
    settings['dsf_aot_estimate'] = 'fixed'

    # CHRIS specific setting
    settings['chris_noise_reduction'] = False
    settings['chris_interband_calibration'] = False

    # process the current bundle
    settings['inputfile'] = l1files
    return settings

def l1_ingest(data_array, outdir, metadata, settings = {}, verbosity = 5, output = None):

    ## parse sensor specific settings
    setu = ac.acolite.settings.parse('CHRIS', settings=settings)
    interband_calibration = setu['chris_interband_calibration']
    noise_reduction = setu['chris_noise_reduction']
    vname = setu['region_name']
    output_radiance = setu['output_lt']
    if output is None: output = setu['output']
    verbosity = setu['verbosity']

    ## get CHRIS interband calibration
    #if interband_calibration: ibcal = ac.chris.interband_calibration()

    #print("Metadata: ",metadata)

    ## extract attributes
    year, month, day = metadata["properties"]['date'].split("T")[0].split('-')
    hour, minutes, seconds = metadata["properties"]['date'].split("T")[1].split("Z")[0].split(':')

    ## date/time
    tc = datetime.datetime(int(year), int(month), int(day), int(hour), int(minutes), int(seconds))
    isodate = tc.isoformat()
    doy = int(tc.strftime('%j'))

    ## target lat/lon
    tlat = float(metadata["geometry"]["coordinates"][1])
    tlon = float(metadata["geometry"]["coordinates"][0])

    ## get view geometry
    angles = metadata["properties"]["acquisitionInformation"][0][
        "acquisitionParameters"]["acquisitionAngles"]
    saa = angles["illuminationAzimuthAngle"]
    sza = angles["illuminationZenithAngle"]
    vza = angles["instrumentZenithAngle"]
    if vza == 0.0: vza = 0.001
    vaa = angles["instrumentAzimuthAngle"]

    ## calculate relative azimuth angle
    raa = np.abs(saa-vaa)
    if raa > 180: raa = np.abs(360-raa)

    ## get bands and mode
    nbands = data_array.sizes["band"]
    #print(data_array)
    ncol = data_array.sizes["x"]
    nrow = data_array.sizes["y"]
    mode = str(
        metadata["properties"]["acquisitionInformation"][0]["acquisitionParameters"][
            "operationalMode"]).strip()
    temp = metadata["properties"]["additionalAttributes"]["temperature"]
    satellite = 'PROBA1'
    bandata = metadata["properties"]["additionalAttributes"]["spectralTable"]
    wavelengths = []
    bandwidths = []
    for count,line in enumerate(bandata.split("\n")):
        if count > 0:
            row = line.split(",")
            if len(row) > 4:
                wavelengths.append(float(row[2]))
                bandwidths.append(float(row[3]))

    gatts = {'sensor':'CHRIS', 'satellite':satellite, \
                'isodate':isodate, 'acolite_file_type': 'L1R',
                'band_waves': wavelengths, 'band_widths': bandwidths,
                'sza': sza, 'vza': vza, 'raa': raa, 'vaa': vaa, 'saa': saa,
                'lat': tlat, 'lon': tlon}

    print("Attributes: {}".format(gatts))
    ofile = '{}/acolite_L1R.nc'.format(outdir)

    ## select interband calibration
    cal = None
    #if interband_calibration:
    #    for c in ibcal:
    #        if (tc >= ibcal[c]['range'][0]) & (tc <= ibcal[c]['range'][1]):
    #            cal = ibcal[c]['data']

    ## set up output file
    gemo = ac.gem.gem(ofile, new=True)
    gemo.gatts = {k: gatts[k] for k in gatts}

    for b in range(nbands):
        wave = '{:.0f}'.format(wavelengths[b])

        # Need to pull across f0 from L1 processing
        ds_att = {'chris_gain': 1.0,
                    'wavelength': wavelengths[b],
                    'width': bandwidths[b],
                    'band_index': b, 'f0': 1.0}

        ## do interband calibration
        #if (interband_calibration) & (cal is not None):
        #    btag = 'band_{}'.format(b+1)
        #    if btag in cal:
        #        bcal = cal[btag]['cal']
        #        cur_data *= bcal
        #        ds_att['interband_calibration'] = bcal
        #        logging.info(wave_f, bcal)

        ## output TOA reflectance
        ds = 'rhot_{}'.format(wave)
        gemo.write(ds, data_array[b, :, :], ds_att = ds_att)
        if verbosity > 2: logging.info('Wrote {} to {}'.format(ds, ofile))
    gemo.close()

    ## apply noise reduction
    #if noise_reduction:
    #    logging.info('Applying CHRIS Noise Reduction')
    #    ofile = ac.chris.noise_reduction(ofile)

    print("Wrote: {}".format(ofile))

    return([ofile], setu)


def acolite_adjustment(data_array, outdir, metadata):

    logging.info("Running ACOLITE")

    # reset run settings to defaults
    ac.settings['run'] = {k:ac.settings['defaults'][k] for k in ac.settings['defaults']}
    time_start = datetime.datetime.now()
    if 'runid' not in ac.settings['run']: ac.settings['run']['runid'] = time_start.strftime('%Y%m%d_%H%M%S')

    ## get user settings
    ## these are updated with sensor specific settings in acolite_l2r/l2w/tact
    settings = setup_settings([], outdir, verbose=False)
    ac.settings['user'] = ac.acolite.settings.parse(None, settings = settings, merge=False)

    ## log file for l1r generation
    log_file = '{}/acolite_run_{}_log_file.txt'.format(ac.settings['run']['output'], ac.settings['run']['runid'])
    log = ac.acolite.logging.LogTee(log_file)

    logging.info('Running ACOLITE processing - {}'.format(ac.version))
    logging.info('Python - {} - {}'.format(ac.python['platform'], ac.python['version']).replace('\n', ''))
    logging.info('Platform - {} {} - {} - {}'.format(ac.system['sysname'], ac.system['release'], ac.system['machine'], ac.system['version']).replace('\n', ''))
    logging.info('Run ID - {}'.format(ac.settings['run']['runid']))

    ## earthdata credentials from settings file
    for k in ['EARTHDATA_u', 'EARTHDATA_p']:
        kv = ac.settings['run'][k] if k in ac.settings['run'] else ac.config[k]
        if len(kv) == 0: continue
        os.environ[k] = kv

    # setup L1 inputs
    ret = l1_ingest(data_array, outdir, metadata, settings = {}, verbosity = 5, output = None)
    if len(ret) != 2:
        l1r = []
    else:
        l1r, _ = ret
    if len(l1r) == 0: raise ValueError("ACOLITE: Unable to convert L1 inputs")
    
    print("Running AC")
    ## do VIS-SWIR atmospheric correction
    if (ac.settings['run']['adjacency_correction']):
        l2r = ac.adjacency.radcor.radcor(l1r[0])
        if l2r is None: l2r = []
    else:
        ret = ac.acolite.acolite_l2r(l1r[0])
        if len(ret) != 2:
            l2r = []
        else:
            l2r, _ = ret
    if len(l1r) == 0: raise ValueError("ACOLITE: Unable to generate L2 product")
        
    print("Generated: {}".format(l2r))

    



    return data_array

```

```python
hdf = False

if hdf:
    path = r"C:\DDrive\Vega\Proba-reprocessing\Initial Test Dataset\ESA-archive-L1\PR1_OPER_CHR_MO3_1P_20040411T181800_N31-006_W110-054_0001.SIP"
    endstr = "*.hdf"
else:
    path = r"\\wsl.localhost\Ubuntu\root\PROBA1_CHRIS\docker-project\app\staging\L2_\Audobon_2004-04-11\cog"    
    endstr = "*.tif"

outpath = os.getcwd()
outdir = os.path.join(outpath,"output")
if not os.path.exists(outdir):
    os.mkdir(outdir)
else:
    outnc = glob.glob(os.path.join(outdir,"*_L2R.nc"))
    if len(outnc) > 0:
        raise SystemExit("Output directory {} not empty".format(outdir))

verbose = True

searchstr = os.path.join(path,endstr)
files = sorted(glob.glob(searchstr))
nfiles = len(files)
if nfiles == 0:
    raise SystemExit("Could not find {}".format(searchstr))
nfiles = 1
print("Found {} files for: {}".format(nfiles,path))

original = False
for nfile in range(nfiles):
    print("{} {}".format(nfile,os.path.basename(files[nfile])))

    # From EO reader
    atcor_inputs = []
    atcor_inputs.append(files[nfile])
    print("Output dir: {}".format(outdir))
    if original:
        run_acolite(atcor_inputs, outdir, verbose = verbose)
    else:
        metadata, data_array, crs, transform = parse_tif(str(files[nfile]))
        acolite_adjustment(data_array, outdir, metadata)

print("Completed")
```
