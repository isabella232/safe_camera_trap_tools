# The `safe_camera_trap_tools` package

Camera traps are a common research tool at the SAFE Project and we want to make sure that camera trap data is well documented and easy to share. This Python 3 package contains two simple tools to help researchers standardise the folder structure of camera trap images into deployments and to extract EXIF data from marked up images into a standard format.

## Requirements

You will need an installation of Python 3.6 or more recent along with the standard library. 

### Exiftool

Image metadata and animal tagging in camera trap images are stored in EXIF data: a set of metadata tags stored within the image file. EXIF data is surprisingly annoying to read in Python. Many libraries exist but few handle much beyond a standard set of tags, leaving a lot of information either unread or as raw hex. The Perl program `exiftool`, which is backed by a gigantic library of tag identifications, is much more powerful. 

Fortunately, it is easily installed:

[https://www.sno.phy.queensu.ca/~phil/exiftool](https://www.sno.phy.queensu.ca/~phil/exiftool)

### Python packages

Using `exiftool` also means that Python needs to be able to talk to it. This requires the installation of the `exiftool` python package, which is available via `pip` as `ocrd-pyexiftool`. The package also uses the `progressbar2` package to report file copying progress,

```bash
pip install ocrd-pyexiftool
pip install progressbar2
```

## Commands

The package contains two core functions: `process_deployment` and `extract_deployment_data`. Both functions are available from within python for use in programs and scripts and as stand-alone command line tools.

## process_deployment

A **deployment** is simply the whole process of putting out a camera trap in a single location for a period of time. This could be for a few days or could be for a month, but this is the basic organisational unit: a location and a time period.

In practice, the camera trap isn't usually just sitting there undisturbed for the whole period. The batteries might need changing, you might run a set of calibration images, the memory card might fill up. The end result is that as a field user, you're almost certainly going to end up with more than one folder of images for a single deployment. If the camera has reset a counter then some of the files in those folders may have the same names (e.g. `IMG_0001.JPG`). Even if this deployment doesn't have the same names, those names are certainly going to crop up in other deployments.

So, this tool takes a location name from the SAFE gazetteer, an output root directory and a set of camera trap image folder names and builds a new single folder containing all the images, with standard informative names. If you have folders of calibration images for a deployment, these will be included in the `CALIB` sub-folder.

**Note**: `process_deployment` does not remove or edit the original folders and images. It also preserves the original file path for an image in the EXIF data of the copied file, under the `PreservedFileName` tag. 

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

### Usage 

The usage notes for using `process_deployment` are:

```sh
usage: process_deployment [-h] [-c CALIB] [--copy]
                          location output_root dir [dir ...]

Compiles folders of images collected from a camera trap into a single deployment folder in
the 'output_root' directory. The deployment folder name is a combination of the provided
'location' name and the earliest date recorded in the EXIF:CreateDate tags in the images. A set
of folders of calibration images can also be provided, which are moved into a single CALIB
directory within the new deployment directory.

When 'copy' is False, which is the default, the image directories are scanned and validated but
the new deployment directory is not created or populated. The new deployment directory is only
created when 'copy' is True. Note that the function **does not delete** the source files when
compiling the new deployment folder.

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
                        A path to a folder of calibration images. Can be
                        repeated to provide more than one folder of
                        calibration images.
  --copy                Use to actually create the deployment rather than just
                        validate.
```

### Example

The repository includes a small `test` directory holding 3 image folders (`test/a`, `test/b`, `test/c`) and 2 calibration folders (`test/cal1`, `test/cal2`). There is only a single image in each, although `test/a` also contains a non-JPEG file.

```
test/a:
    Image_1.jpg
    badfile.png
test/b:
    Image_1.jpg
test/c:
    Image_1.jpg
test/cal1:
    Calib_1.jpg
test/cal2:
    Calib_1.jpg
```

Using `process_deployment` to handle this test dataset consists of:

1. Create a root directory to hold the restructured deployment:

        mkdir deployments

2. Run the tool, specifiying the location (e.g. `F100-1-1`) and the new output folder:

        python3 ./process_deployment.py F100-1-1 deployments test/a test/b test/c \
                -c test/cal1 -c test/cal2 --copy

This should print the following output:

```
Processing directory: test/a
 - Found 1 JPEG files
 - *!* Found 1 other files: badfile.png
 - Scanning EXIF data
Processing directory: test/b
 - Found 1 JPEG files
 - Scanning EXIF data
Processing directory: test/c
 - Found 1 JPEG files
 - Scanning EXIF data
Processing directory: test/cal1
 - Found 1 JPEG files
 - Scanning EXIF data
Processing directory: test/cal2
 - Found 1 JPEG files
 - Scanning EXIF data
Copying files:
100% (5 of 5) |######################| Elapsed Time: 0:00:00 Time:  0:00:00
```

The result will be the following folder structure in `deployments`:

```
deployments/F100-1-1_20160518:
CALIB
F100-1-1_20160518_202256_1.jpg
F100-1-1_20160518_202257_2.jpg
F100-1-1_20160518_202258_3.jpg
deployments//F100-1-1_20160518/CALIB:
F100-1-1_20160518_202258_4.jpg
F100-1-1_20160518_202259_5.jpg
```

## `extract_deployment_data`

This extracts EXIF data from the images and calibration images within a deployment folder and creates a text output file containing key EXIF fields. In particular, it looks for the `IPTC:Keywords` tag. This field is used to store image annotation data, following a set of numeric tags, for example `15: F100-1-1` records the location, `1: Crested Fireback` records a species in an image and `24: Phil` records that Phil Chapman assessed the image.

The command runs some simple validation to check that the deployment details are consistent and then saves a tab-delimited text file. Deployment level data (camera type, start date, etc) are written as a header and then a table of image data follows a separator line ('---').

### Usage

```
usage: extract_deployment_data [-h] [-o OUTFILE] deployment

This script takes a single deployment folder and extracts EXIF data for the deployment
into a tab delimited file. By default, the data is written to a file `exif_data.dat` 
within the deployment directory.

positional arguments:
  deployment            A path to a deployment directory

optional arguments:
  -h, --help            show this help message and exit
  -o OUTFILE, --outfile OUTFILE
                        An output file name
```

