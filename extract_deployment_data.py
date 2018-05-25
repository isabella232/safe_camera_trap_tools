import os
import sys
import argparse
import exiftool
import pandas
from itertools import groupby
import datetime

"""
This script takes a single deployment folder and extracts EXIF data and other 
statistics into a common format. It duplicates the information extracted by an 
earlier tool written in R that extracted EXIF data from an exiftool dump to csv
for a folder.  
"""


def extract_deployment_data(deployment, outfile=None):

    """
    This function takes a

    Args:
        deployment: A path to a deployment directory
        outfile: A path to a file to hold the extracted data, defaulting to the
            deployment folder name + '_exif_data.csv'
    Returns:

    """

    # get an exifread.ExifTool instance
    et = exiftool.ExifTool()
    et.start()

    # Check the deployment folder exists
    if not os.path.exists(deployment) and os.path.isdir(deployment):
        raise IOError('Deployment path does not exist or is not a directory.')

    if outfile is None:
        outfile = deployment + '_exif_data.csv'

    images = os.listdir(deployment)
    images = [im for im in images if im.lower().endswith('.jpg')]
    sys.stdout.write(' - Extracting data from {} images in {}\n'.format(len(images), deployment))
    sys.stdout.flush()

    # Get a list of JPG images and get their exif data - for large directories,
    # this could be a pretty big chunk of data - and then convert to a pandas dataframe
    # and convert the creation date strings to pandas Timestamps
    images = os.listdir(deployment)
    images = [im for im in images if im.lower().endswith('.jpg')]
    images_exif = et.get_metadata_batch([os.path.join(deployment, im) for im in images])
    images_exif = pandas.DataFrame(images_exif)
    images_exif["EXIF:CreateDate"] = pandas.to_datetime(images_exif["EXIF:CreateDate"],
                                                        format='%Y:%m:%d %H:%M:%S')

    # Check for a calib directory
    calib_dir = os.path.join(deployment, 'calib')
    if os.path.exists(calib_dir):
        # get exif data from calibration images
        calib = os.listdir(calib_dir)
        calib = [im for im in calib if im.lower().endswith('.jpg')]
        calib_exif = et.get_metadata_batch([os.path.join(calib_dir, im) for im in calib])
        calib_exif = pandas.DataFrame(calib_exif)
        calib_exif["EXIF:CreateDate"] = pandas.to_datetime(calib_exif["EXIF:CreateDate"],
                                                           format='%Y:%m:%d %H:%M:%S')
    else:
        # empty placeholders to use in rest of processing
        calib = []
        calib_exif = images_exif.iloc[0:0]

    # DEPLOYMENT level data

    # get the date range
    dep_data = pandas.concat([images_exif, calib_exif], axis=0)
    start_dt =  dep_data["EXIF:CreateDate"].min()
    end_dt =  dep_data["EXIF:CreateDate"].max()
    n_days = (end_dt - start_dt).ceil('D').days

    # reduce to the deployment level tags
    dep_tags = ['EXIF:Make', 'EXIF:Model', 'MakerNotes:SerialNumber',
                'MakerNotes:FirmwareDate', 'File:ImageHeight', 'File:ImageWidth']
    dep_data = pandas.concat([images_exif[dep_tags], calib_exif[dep_tags]], axis=0)

    # The data in all these rows should be identical
    dep_data.drop_duplicates(inplace=True)
    if dep_data.shape[0] > 1:
        raise RuntimeError('Deployment level data is not consistent')

    dep_data['n_images'] = len(images)
    dep_data['n_calib'] = len(calib)
    dep_data['start'] = str(start_dt)
    dep_data['end'] = str(end_dt)
    dep_data['n_days'] = n_days

    # transpose the data to give rows
    dep_data.transpose().to_csv(outfile)

    # parse the keywords data to a dictionary for each row, allowing for repeated keywords
    # and then convert that into a pandas dataframe with a column for each tag number
    def kw_dict(kw_list):
        kw_list = [kw.split(':') for kw in kw_list]
        kw_list.sort(key=lambda x: x[0])
        kw_groups = groupby(kw_list, key=lambda x: x[0])
        kw_dict = dict([(k, ', '.join(vl[1] for vl in vals)) for k, vals in kw_groups])
        return kw_dict

    keywords = images_exif['IPTC:Keywords'].apply(kw_dict)
    keywords = pandas.DataFrame(list(keywords))

    # add image information to the keyword data
    image_info = ["File:FileName", "EXIF:CreateDate", "EXIF:ExposureTime", "EXIF:ISO",
                  "EXIF:Flash", "MakerNotes:InfraredIlluminator", "MakerNotes:MotionSensitivity",
                  "MakerNotes:AmbientTemperature", "EXIF:SceneCaptureType",
                  "MakerNotes:Sequence", "MakerNotes:TriggerMode"]

    image_data =  pandas.concat([images_exif[image_info], keywords], axis=1)
    image_data.to_csv(outfile, mode='a')

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
    parser.add_argument('-o', '--outfile', default=None,
                        help='A path to a file to hold the extracted data')

    args = parser.parse_args()

    extract_deployment_data(deployment=args.deployment, outfile=args.outfile)


if __name__ == "__main__":
    main()
