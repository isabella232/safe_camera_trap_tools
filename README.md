# safe_camera_trap_tools

Camera traps are a common research tool at the SAFE Project and we want to make sure that camera trap
data is well documented and easy to share. This repository contains two simple tools to help researchers
standardise the folder structure of camera trap images into deployments and to extract EXIF data from 
marked up images into a standard format.

## Requirements
Both tools require the PERL program `exiftool` to be installed: [https://www.sno.phy.queensu.ca/~phil/exiftool/].
This program is widely supported across platforms and provides fantastic support for reading EXIF data from images. 
EXIF data is messy - there are some standard tags but hardware and software manufacturers can make up their own tags,
which often contain important information: `exiftool` includes a unique database of EXIF tags and 
possible values from a very wide range of sources.

This also means that Python needs to be able to talk to `exifttool`. For this, the program uses a simple interface 
package which can be installed as follow:

```bash
pip install ocrd-pyexiftool
```

## process_deployment

A **deployment** is simply the whole process of putting out a camera trap in a single location for a period 
of time. This could be for a few days or could be for a month, but this is the basic organisational unit: 
a point in space and a time period.

In practice, the camera trap isn't usually just sitting there undisturbed for the whole period. The batteries
might need changing, you might run a set of calibration images, the memory card might fill up. The end result 
is that as a field user, you're almost certainly going to end up with more than one folder of images for a 
single deployment. If the camera has reset a counter then some of the files in those folders may have the same
names (e.g. `IMG_0001.JPG`). Even if this deployment doesn't have the same names, those names are 
certainly going to crop up in other deployments.

So, this tool takes a location name from the SAFE gazetteer, an output root directory and a set of camera trap
image folder names and builds a new single folder containing all the images, with standard informative names. If
you have a folder of calibration images for a deployment, that can be included as a sub-folder.

So, for example, the final deployment folder might look like this:

```
D100-1-11_20150612/
    calib/
        D100-1-11_20150612_111423_0.jpg
        ...
    D100-1-11_20150613_094512_1.jpg    
    D100-1-11_20150613_094512_2.jpg    
    D100-1-11_20150613_094513_3.jpg    
    ...
```

### Usage

```process_deployment.py [-h] [-c CALIB] location output_root N [N ...]```

This program consolidates a set of camera trap image folders from a single
deployment into a single folder, renaming the images to a standardised format.
It does _not_ alter the original folders: all of the images are copied into a
new folder. It also checks that all of the new images are getting unique names
before starting to copy files.

```
positional arguments:
  location              A SAFE location code from the gazetteer that will be
                        used in the folder and file names.
  output_root           A path to the directory where the deployment folder is
                        to be created.
  N                     Paths for each directory to be included in the
                        deployment folder.

optional arguments:
  -h, --help            show this help message and exit
  -c CALIB, --calib CALIB
                        A path to a folder of calibration images for the
                        deployment.
```

