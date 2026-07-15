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
from datetime import datetime, timedelta

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
```

```python
# Run acolite for each file
def run_acolite(s2l1files, outdir, l2prods = False, verbose = False):
    
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
    settings['chris_noise_reduction']=False
    settings['chris_interband_calibration']=False

```

```python
path = r"C:\DDrive\Vega\Proba-reprocessing\Initial Test Dataset\ESA-archive-L1\PR1_OPER_CHR_MO3_1P_20040411T181800_N31-006_W110-054_0001.SIP"    
outpath = os.path.dirname(os.getcwd())
outdir = os.path.join(outpath,"output")
if not os.path.exists(outdir):
    os.mkdir(outdir)

files = sorted(glob.glob(os.path.join(path,"*.hdf")))
nfiles = len(files)
nfiles = 1
print("Found {} files for: {}".format(nfiles,path))

for nfile in range(nfiles):
    print("{} {}".format(nfile,os.path.basename(files[nfile])))

    # From EO reader
    tile_name = os.path.basename(files[nfile]).split("_")[5]
    atcor_inputs = []
    atcor_inputs.append(files[nfile])
    print("Output dir: {}".format(outdir))
    run_acolite(atcor_inputs, outdir, l2prods=True)

print("Completed")
```

```python

```
