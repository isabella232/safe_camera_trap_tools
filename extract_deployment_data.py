import os
import sys
import argparse
import progressbar
import shutil
import exiftool
import datetime

# pip install ocrd-pyexiftool


"""
This script takes a single deployment folder and extracts EXIF data and other 
statistics into a common format
"""


def extract_deployment_data(deployment, outfile):

    """
    This function takes a

    Args:
        deployment: A path to a deployment directory
        outfile: A path to a file to hold the extracted data
    Returns:

    """

    # get an exifread.ExifTool instance
    et = exiftool.ExifTool()
    et.start()

    # tidy up
    et.terminate()


def main():

    """
    This program consolidates a set of camera trap image folders from a single
    deployment into a single folder, renaming the images to a standardised format.

    It does _not_ alter the original folders: all of the images are copied into
    a new folder. It also checks that all of the new images are getting unique names
    before starting to copy files.
    """

    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument('deployment',
                        help='A path to a deployment directory')
    parser.add_argument('outfile',
                        help='A path to a file to hold the extracted data')

    args = parser.parse_args()

    extract_deployment_data(deployment=args.deployment, outfile=args.outfile)


if __name__ == "__main__":
    main()
