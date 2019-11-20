# safe_camera_trap_tools

Camera traps are a common research tool at the SAFE Project and we want to make sure that camera trap data is well documented and easy to share. This repository contains two simple tools to help researchers standardise the folder structure of camera trap images into deployments and to extract EXIF data from marked up images into a standard format.

## Requirements

You will need an installation of Python along with the standard library. You will need to use Python 3.6 or more recent.

Both tools require the PERL program `exiftool` to be installed:  

[https://www.sno.phy.queensu.ca/~phil/exiftool](https://www.sno.phy.queensu.ca/~phil/exiftool)

This program is widely supported across platforms and provides fantastic support for reading EXIF data from images. EXIF data is messy - there are some standard tags but hardware and software manufacturers can make up their own tags, which often contain important information: `exiftool` includes a unique database of EXIF tags and possible values from a very wide range of sources.

This also means that Python needs to be able to talk to `exifttool`. For this, the program uses a simple interface package which can be installed as follows:

```bash
pip install ocrd-pyexiftool
```

## process_deployment

A **deployment** is simply the whole process of putting out a camera trap in a single location for a period of time. This could be for a few days or could be for a month, but this is the basic organisational unit: a point in space and a time period.

In practice, the camera trap isn't usually just sitting there undisturbed for the whole period. The batteries might need changing, you might run a set of calibration images, the memory card might fill up. The end result is that as a field user, you're almost certainly going to end up with more than one folder of images for a single deployment. If the camera has reset a counter then some of the files in those folders may have the same names (e.g. `IMG_0001.JPG`). Even if this deployment doesn't have the same names, those names are certainly going to crop up in other deployments.

So, this tool takes a location name from the SAFE gazetteer, an output root directory and a set of camera trap image folder names and builds a new single folder containing all the images, with standard informative names. If you have folders of calibration images for a deployment, these will be included in the `CALIB` sub-folder.

The standard name structure that will be created by the tool is:

* The deployment folder name must have the format `location_YYYYMMDD`, where `location` is a location name from the SAFE gazetteer and the date is the start date of the deployment. The start date is extracted automatically as the date of the earliest image.
* Image names must have the format `location_YYYYMMDD_HHMMSS_#`: the same as the deployment, plus the time that the image was taken and the image sequence number (`#`). 
    This last number is because cameras firing in burst mode can easily take multiple images in the same second, so we need the unique sequence number in the burst to separate them. If the image isn't in a sequence, then the number 0 is used: it is easier to parse file names if they all have the same structure.

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

The original file path for the file is stored in the image in the EXIF data, under the `PreservedFileName` tag.

### Usage

The usage notes for using `process_deployment.py` from the command line are:

    process_deployment.py [-h] [-c CALIB] [--copy] [--report REPORT]
                          location output_root dir [dir ...]

    This program consolidates a set of camera trap image folders from a single
    deployment into a single folder, renaming the images to a standardised format.
    It does _not_ alter the original folders: all of the images are copied into a
    new folder. It also checks that all of the new images are getting unique names
    before starting to copy files.
    
    positional arguments:
      location              A SAFE location code from the gazetteer that will be
                            used in the folder and file names.
      output_root           A path to the directory where the deployment folder is
                            to be created.
      dir                   Paths for each directory to be included in the
                            deployment folder.
    
    optional arguments:
      -h, --help            show this help message and exit
      -c CALIB, --calib CALIB
                            A path to a folder of calibration images for the
                            deployment. This option can be used multiple times to
                            include more than one folder of calibration images.
      --copy                By default, the program runs checking and prints out
                            validation messages. It will only actually copy new
                            files into their new locations if this option is
                            specified.
      --report REPORT       If key EXIF tags are missing, up to this many problem
                            filenames are provided to help troubleshoot.

