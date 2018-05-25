import os
import sys
import argparse
import exiftool
import pandas
from itertools import groupby
import re

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
        outfile: A path to a file to hold the extracted data as tab delimited text,
            defaulting to saving the data as 'exif_data.dat' within the deployment directory
    """

    # get an exifread.ExifTool instance
    et = exiftool.ExifTool()
    et.start()

    # Check the deployment folder exists
    if not os.path.exists(deployment) and os.path.isdir(deployment):
        raise IOError('Deployment path does not exist or is not a directory.')

    if outfile is None:
        outfile = os.path.join(deployment, 'exif_data.csv')

    images = os.listdir(deployment)
    images = [im for im in images if im.lower().endswith('.jpg')]

    # check for any calibration images
    calib_dir = os.path.join(deployment, 'calib')
    if os.path.exists(calib_dir):
        # get exif data from calibration images
        calib = os.listdir(calib_dir)
        calib = [im for im in calib if im.lower().endswith('.jpg')]
    else:
        calib = []

    sys.stdout.write('Extracting data from {}\n '
                     ' - {} images found\n '
                     ' - {} calibration_images found\n'.format(deployment, len(images), len(calib)))
    sys.stdout.flush()

    # get exif data for images and then convert to a pandas dataframe
    images_exif = et.get_metadata_batch([os.path.join(deployment, im) for im in images])
    images_exif = pandas.DataFrame(images_exif)

    # If any, get the same exif data for calibration images
    if calib:
        calib_exif = et.get_metadata_batch([os.path.join(calib_dir, im) for im in calib])
        calib_exif = pandas.DataFrame(calib_exif)
    else:
        # empty placeholders to use in rest of processing
        calib = []
        calib_exif = images_exif.iloc[0:0]

    # Simplify EXIF tag names to remove EXIF group and combine the image
    # and calibration image data
    exif_group = re.compile('[A-z]+:')
    images_exif.columns = [exif_group.sub('', vl) for vl in images_exif.columns]
    calib_exif.columns = [exif_group.sub('', vl) for vl in calib_exif.columns]
    images_exif['Calib'] = 0
    calib_exif['Calib'] = 1
    images_exif =  pandas.concat([images_exif, calib_exif], axis=0)

    # convert creation date to timestamp
    images_exif["CreateDate"] = pandas.to_datetime(images_exif["CreateDate"],
                                                   format='%Y:%m:%d %H:%M:%S')

    #  EXTRACT KEYWORD TAGGING
    # conversion function
    def kw_dict(kw_list):
        """
        Takes a list of keyword lists (one list for each image) and returns
        them as a list of dictionaries, keyed by keyword tag number. Combines
        duplicate tag numbers and strips whitespace padding.

        For example:
        [['15: E100-2-23', '16: Person', '16: Setup', '24: Phil'], [...
        goes to
        [{'15': 'E100-2-23', '16': 'Person, Setup', '24': 'Phil'}, {...
        """
        kw_list = [kw.split(':') for kw in kw_list]
        kw_list.sort(key=lambda x: x[0])
        kw_groups = groupby(kw_list, key=lambda x: x[0])
        kw_dict = dict([(k, ', '.join(vl[1].strip() for vl in vals)) for k, vals in kw_groups])
        return kw_dict

    if 'Keywords' not in images_exif:
        sys.stderr.write(' ! Image tagging keywords not found')
        sys.stderr.flush()
        keywords = pandas.DataFrame()
    else:
        # convert the keywords from a single exif tag into a data frame with
        # tag numbers as keys
        keywords = images_exif['Keywords'].apply(kw_dict)
        keywords = pandas.DataFrame(list(keywords))
        keywords.columns = ['Tag_' + tg for th in keywords.columns]
        images_exif = pandas.concat([images_exif, keywords], axis=1)

    # DEPLOYMENT level data
    sys.stdout.write('Checking for consistent deployment data\n')

    # check camera data
    dep_data = images_exif['Make', 'Model', 'SerialNumber', 'FirmwareDate',
                              'ImageHeight', 'ImageWidth']
    dep_data.drop_duplicates(inplace=True)

    if dep_data.shape[0] > 1:
        sys.stderr.write(' ! Camera data is not consistent')
        sys.stderr.flush()

    # check location data (only keyword tag that should be constant)
    if 'Tag_15' not in images_exif:
        sys.stderr.write(' ! No location tags (15) found\n')
        sys.stderr.flush()
    else:
        locations = df.Tag_15.unique()
        if len(locations) > 1:
            sys.stderr.write(' ! Location tags (15) not consistent:'
                             ' {}\n'.format(', '.join(locations)))
            sys.stderr.flush()
        dep_data['Location'] = locations
    
    if 'CreateDate' not in images_exif:
        sys.stderr.write(' ! No CreateDate tags found\n')
        sys.stderr.flush()
    else:
        # get the date range
        start_dt =  images_exif["CreateDate"].min()
        end_dt =  images_exif["CreateDate"].max()
        n_days = (end_dt - start_dt).ceil('D').days
        dep_data['start'] = str(start_dt)
        dep_data['end'] = str(end_dt)
        dep_data['n_days'] = n_days

    dep_data['n_images'] = len(images)
    dep_data['n_calib'] = len(calib)
    n_total = len(images) +len(calib)

    # transpose the data to give a set of header rows
    dep_data = dep_data.transpose()

    # print to screen to report
    print(dep_data.to_csv(header=False))

    # IMAGE level data
    # report on keyword tag completeness:
    if not keywords.empty:
        kw_tag_count = keywords.count()
        kw_tag_txt = [ str(ct) + ' / ' +  str(n_total)  for ct in kw_tag_count]
        kw_df = pandas.DataFrame(data={'tag': kw_tag_count.index, 'count':kw_tag_txt})
        print(kw_df.to_csv(header=None, sep='\t'))

    # write required field to output file
    image_info = ["FileName", "CreateDate", "ExposureTime", "ISO", "Flash",
                  "InfraredIlluminator", "MotionSensitivity", "AmbientTemperature",
                  "SceneCaptureType", "Sequence", "TriggerMode"] + keywords.columns

    images_exif[image_info].to_csv(outfile, mode='a', sep='\t', index=None)

    # tidy up
    sys.stdout.write('Data written to {}\n'.format(outfile))
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
