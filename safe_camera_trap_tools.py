import os
import sys
import argparse
import datetime
import csv
import shutil
from itertools import groupby
from collections import OrderedDict
import textwrap
import re
import exiftool
import progressbar


# TODO - Figure out how to share the docstrings between the functions and their CLI wrappers

def _process_folder(image_dir, location, et):

    """
    This private function processes a single folder of images. It reads the EXIF data for each JPEG
    file in the folder and uses this and the provided location name to create the new filename. It
    also tracks and returns the earliest creation datetime, used to create the deployment folder
    name.
    
    Args:
        image_dir: The directory to process
        location: The name of the location to be used as the deployment name
        et: An exiftool instance
    
    Returns:
        A list of two-tuples [(file_name, new_name)] and the earliest creation date found as a
        datetime.datetime object.
    """

    print(f'Processing directory: {image_dir}', file=sys.stdout, flush=True)
    
    # Load list of files, ignoring nested directories and separate JPEGS
    files =  next(os.walk(image_dir))[2]
    jpeg_files = [fl for fl in files if fl.lower().endswith('jpg')]
    other_files = set(files) - set(jpeg_files) 
    
    # report on what is found
    print(f' - Found {len(jpeg_files)} JPEG files', file=sys.stdout, flush=True)

    if other_files:
        print(f' - *!* Found {len(other_files)} other files: {", ".join(other_files)}',
              file=sys.stdout, flush=True)
    
    # Handle folders with no images:
    if len(jpeg_files):
        print(' - Scanning EXIF data', file=sys.stdout, flush=True)

        # get full paths
        paths = [os.path.join(image_dir, fl) for fl in jpeg_files]

        # get creation date and sequence tag from EXIF
        tags = ['EXIF:CreateDate', u'MakerNotes:Sequence']
        tag_data = et.get_tags_batch(tags, paths)

        # check tags found and report first five file names
        for tag_check in tags:
            tag_missing = [fl for fl, tg in zip(files, tag_data) if tag_check not in tg]
            if len(tag_missing):
                n_missing = len(tag_missing)
                report_n = 5
                report_missing = ','.join(tag_missing[0:report_n])
                if report_n < n_missing:
                    report_missing += ", ..."
                raise RuntimeError(f'{n_missing} files missing {tag_check} tag: {report_missing}')
    
        # Generate new file names:
        # a) Get file datetimes
        create_date = [datetime.datetime.strptime(td['EXIF:CreateDate'], '%Y:%m:%d %H:%M:%S')
                       for td in tag_data]
        # b) in burst mode, time to seconds is not unique, so add sequence number
        sequence = ['_' + td[u'MakerNotes:Sequence'].split()[0] for td in tag_data]
        # c) put those together
        new_name = [location + "_" + dt.strftime("%Y%m%d_%H%M%S") + seq + ".jpg"
                    for dt, seq in zip(create_date, sequence)]
    
        # Get earliest date
        min_date = min(create_date)
    
        # Return a list of tuples [(src, dest), ...] and the earliest creation date
        return(list(zip(paths, new_name)), min_date)
    else:
        return([], datetime.datetime(1,1,1))


def process_deployment(image_dirs, location, output_root, calib_dirs=[], copy=False):

    """Compiles folders of images collected from a camera trap into a single deployment folder in
    the 'output_root' directory. The deployment folder name is a combination of the provided
    'location' name and the earliest date recorded in the EXIF:CreateDate tags in the images. A set
    of folders of calibration images can also be provided, which are moved into a single CALIB
    directory within the new deployment directory.
    
    When 'copy' is False, which is the default, the image directories are scanned and validated but
    the new deployment directory is not created or populated. The new deployment directory is only
    created when 'copy' is True. Note that the function **does not delete** the source files when
    compiling the new deployment folder.

    Args:
        image_dirs: A list of directories containing camera trap images
        location: The name of the location to be used as the deployment name
        output_root: The location to compile the deployment folder to
        calib: An optional list of directories of calibration images.
        copy: Boolean

    Returns:
        The name of the resulting deployment directory
    """

    # check the output root directory
    if not os.path.isdir(output_root):
        raise IOError('Output root directory not found')

    # Check image and calib directories exist and are directories
    input_dirs = image_dirs + calib_dirs
    bad_dir = [dr for dr in input_dirs if not os.path.isdir(dr)]
    if bad_dir:
        raise IOError('Directories not found: {}'.format(', '.join(bad_dir)))

    # get an exifread.ExifTool instance
    et = exiftool.ExifTool()
    et.start()
    
    # Process image folders
    image_data = [_process_folder(f, location, et) for f in image_dirs]
    dates = [dat[1] for dat in image_data]
    files = [dat[0] for dat in image_data]
    files = [item for sublist in files for item in sublist]
    
    # Process calibration folders
    if calib_dirs is not None:
        calib_data = [_process_folder(f, location, et) for f in calib_dirs]
        dates += [dat[1] for dat in calib_data]
        calib_files = [dat[0] for dat in calib_data]
        calib_files = [item for sublist in calib_files for item in sublist]
        files += [(src, os.path.join('CALIB', dest)) for src, dest in calib_files]
    
    # Look for file name collisions across the whole set
    all_new_file_names = [f[1] for f in files]
    if len(all_new_file_names) > len(set(all_new_file_names)):
        raise RuntimeError('Duplication found in new image names.')
    
    
    # get the final directory name and check it doesn't already exist
    outdir = '{}_{}'.format(location, min(dates).strftime("%Y%m%d"))
    outdir = os.path.abspath(os.path.join(output_root, outdir))
    if os.path.exists(outdir):
        raise IOError('Output directory already exists:\n    {}'.format(outdir))
    elif copy:
        os.mkdir(outdir)
        if calib_dirs is not None:
            os.mkdir(os.path.join(outdir, 'CALIB'))

    if copy:
        # move the files and insert the original file location into the EXIF metadata
        print('Copying files:\n', file=sys.stdout, flush=True)
        
        with progressbar.ProgressBar(max_value=len(files)) as bar:
            for idx, (src, dst) in enumerate(files):
                # Copy the file
                dst = os.path.join(outdir, dst)
                shutil.copyfile(src, dst)
                # Insert original file name into EXIF data
                tag_data = f'-XMP-xmpMM:PreservedFileName={src}'
                et.execute(b'-overwrite_original', tag_data.encode('utf-8'), exiftool.fsencode(dst))
                bar.update(idx)
    
    # tidy up
    et.terminate()
    
    return outdir


def extract_deployment_data(deployment, outfile=None):

    """Extracts the key EXIF data from a deployment folder, creating a tab-delimited output file
    holding image level data with a short header of deployment level data.
    
    Args:
        deployment: A path to a deployment directory
        outfile: A path to a file to hold the extracted data as tab delimited text,
            defaulting to saving the data as 'exif_data.dat' within the deployment 
            directory
    """

    # LOAD THE EXIF DATA FROM IMAGE AND CALIB DIRECTORIES
    # get an exifread.ExifTool instance
    et = exiftool.ExifTool()
    et.start()

    # Check the deployment folder exists
    if not os.path.exists(deployment) and os.path.isdir(deployment):
        raise IOError('Deployment path does not exist or is not a directory.')

    if outfile is None:
        outfile = os.path.join(deployment, 'exif_data.csv')

    print(f'Extracting EXIF data from {deployment}', file=sys.stdout, flush=True)

    # Find images, extract EXIF data and flag as non-calibration images
    images = os.listdir(deployment)
    images = [im for im in images if im.lower().endswith('.jpg')]
    images_exif = et.get_metadata_batch([os.path.join(deployment, im) for im in images])
    _ =[entry.update({'Calib': 0}) for entry in images_exif]

    # check for any calibration images
    calib_dir = os.path.join(deployment, 'CALIB')
    if os.path.exists(calib_dir):
        # get exif data from calibration images
        calib = os.listdir(calib_dir)
        calib = [im for im in calib if im.lower().endswith('.jpg')]
        calib_exif = et.get_metadata_batch([os.path.join(calib_dir, im) for im in calib])
        _ =[entry.update({'Calib': 1}) for entry in calib_exif]
    else:
        calib_exif = []
    
    # Combine and continue
    exif = images_exif + calib_exif
    n_exif = len(exif)
    
    # Reduce to tags used in rest of the script, filling in blanks and simplifying tag names
    keep_tags = ['EXIF:Make', 'EXIF:Model', 'MakerNotes:SerialNumber', 'Calib',
                 'MakerNotes:FirmwareDate', 'File:ImageHeight', 'File:ImageWidth',
                 "File:FileName", "EXIF:CreateDate", "EXIF:ExposureTime", "EXIF:ISO",
                 "EXIF:Flash", "MakerNotes:InfraredIlluminator", "MakerNotes:MotionSensitivity",
                 "MakerNotes:AmbientTemperature", "EXIF:SceneCaptureType",
                 "MakerNotes:Sequence", "MakerNotes:TriggerMode", 'IPTC:Keywords']
    
    # convert keep_tags to 2-tuples of current name and simplified name
    exif_group = re.compile('[A-z]+:')
    keep_tags = [(vl, exif_group.sub('', vl)) for vl in keep_tags]
    
    for idx, entry in enumerate(exif):
        exif[idx] = {short_key: entry.get(long_key, None) for long_key, short_key in keep_tags}
    
    # EXTRACT KEYWORD TAGGING - The image tagging process populates the IPTC:Keywords tag
    # with a list of tags that need to be expanded out into their own fields in the output.
    
    # 1) First, unpack keywords into a subdictionary if they are present
    #    The keywords are strings with the format 'tag_number: value', where tag 
    #    number can be repeated. The process below combines duplicate tag numbers 
    #    and strips whitespace padding.
    #    
    #    For example:
    #    ['15: E100-2-23', '16: Person', '16: Setup', '24: Phil']
    #    goes to
    #    {'15': 'E100-2-23', '16': 'Person, Setup', '24': 'Phil'}
    
    
    for entry in exif:
        if entry['Keywords'] is None:
            entry['Keywords'] = {}
        else:
            # Single keywords can be loaded as a string not a list of string
            keywords = entry['Keywords']
            if isinstance(keywords, str):
                keywords = [keywords]
            # Split the strings on colons
            kw_list = [kw.split(':') for kw in keywords]
            # Sort and group on tag number
            kw_list.sort(key=lambda x: x[0])
            kw_groups = groupby(kw_list, key=lambda x: x[0])
            # Turn that into a dictionary 
            kw_dict = {}
            for key, vals in kw_groups:
                kw_dict['Tag_' + key] = ', '.join(vl[1].strip() for vl in vals)
            # Replace the original list with the new dictionary
            entry['Keywords'] = kw_dict
    
    # 2) Find the common set of tags, in order to populate the file dictionaries
    #    with complete entries, including blanks for missing tags
    keyword_tags = [list(d['Keywords'].keys()) for d in exif]
    keyword_tags = set([tg for tag_list in keyword_tags for tg in tag_list])
    
    # 3) Move the keyword tags from inside entry['Keywords'] to entry, 
    #    populating the full set of tags in the deployment along the way 
    #    and then delete entry['Keywords']
    for entry in exif:
        keywords = entry['Keywords']
        keywords = {tag: keywords.get(tag, None) for tag in keyword_tags}
        entry.update(keywords)
        del entry['Keywords']
    
    # REPORTING AND VALIDATION
    
    # Get dictionary of fields - processing so far using dict.get(vl, None)
    # should ensure that all keys are present for all files.
    exif_fields = {k: [dic[k] for dic in exif] for k in exif[0]}
    
    # DEPLOYMENT level data
    print('Checking for consistent deployment data', file=sys.stdout, flush=True)
    dep_data = OrderedDict()
    
    # A) Check for consistent camera data
    camera_fields = ['Make', 'Model', 'SerialNumber', 'FirmwareDate',
                     'ImageHeight', 'ImageWidth']
    
    for fld in camera_fields:
        vals = set(exif_fields[fld])
        if len(vals) > 1:
            vals = ', '.join(vals)
            print(f"  ! {fld} is not consistent: {vals}", file=sys.stderr, flush=True)
        else:
            vals = list(vals)[0]
        
        dep_data[fld] = vals
    
    # B) Check for date information 
    #    EXIF should have a consistent datetime format: "YYYY:mm:dd HH:MM:SS"
    image_dates = [datetime.datetime.strptime(vl, '%Y:%m:%d %H:%M:%S') 
                   for vl in exif_fields['CreateDate'] if vl is not None]
    
    if not image_dates:
        print('  ! No CreateDate tags found', file=sys.stderr, flush=True )
    else:
        # get the date range
        start_dt = min(image_dates)
        end_dt = max(image_dates)
        n_days = (end_dt - start_dt).days + 1
        dep_data['start'] = str(start_dt)
        dep_data['end'] = str(end_dt)
        dep_data['n_days'] = n_days
        
        # report on missing dates
        if len(image_dates) < n_exif:
            print(f'  ! CreateDate tags not complete: {len(image_dates)}/{n_exif}', 
                  file=sys.stderr, flush=True)
            dep_data['n_missing_dates'] = n_exif - len(image_dates)
    
    # C) Check location data (only keyword tag that should be constant)
    if 'Tag_15' not in exif_fields:
        print('  ! No location tags (15) found', file=sys.stderr, flush=True)
    else:
        # Get the unique tagged locations
        locations = set(exif_fields['Tag_15'])
        
        # Are they consistent with the deployment folder
        match_folder = [os.path.basename(deployment).startswith(l) for l in locations]
        
        if len(locations) > 1:
            locations = ', '.join(locations)
            print(f'  ! Location tags (15) not internally consistent: {locations}',
                  file=sys.stderr, flush=True)
        else:
            locations = list(locations)[0]
        
        if not any(match_folder):
            print('  ! Location tags (15) do not match deployment folder.',
                  file=sys.stderr, flush=True)
        
        dep_data['location'] = locations
    
    # Add the number of images
    dep_data['n_images'] = len(images_exif)
    dep_data['n_calib'] = len(calib_exif)
    
    # print to screen to report
    print('Deployment data:', file=sys.stdout, flush=True)
    dep_lines = [f'{ky}: {vl}' for ky, vl in dep_data.items()]
    print(*['    ' + d +'\n' for d in dep_lines], file=sys.stdout, flush=True)
    
    # IMAGE level data
    # report on keyword tag completeness:
    if not keyword_tags:
        print(' ! No Image keyword tags found', file=sys.stderr, flush=True)
    else:
        print('Image tag counts:', file=sys.stdout, flush=True)
        for kywd in keyword_tags:
            n_found = sum([vl is not None for vl in exif_fields[kywd]])
            print(f'    {kywd:10}{n_found:6}', file=sys.stdout, flush=True)
    
    # WRITE data to files
    with open(outfile, 'w') as outf:
        # Header containing constant deployment data
        outf.writelines(ln + '\n' for ln in dep_lines)
        outf.write('---\n')
    
    with open(outfile, 'a') as outf:
        # Tab delimited table of image data
        writer = csv.writer(outf, delimiter='\t', lineterminator='\n')
        data = zip(*exif_fields.values())
        writer.writerow(exif_fields.keys())
        writer.writerows(data)
    
    # tidy up
    print(f'Data written to {outfile}', file=sys.stdout, flush=True)
    et.terminate()


"""
Command line interfaces to the two functions
"""


def _process_deployment_cli():

    """
    Compiles folders of images collected from a camera trap into a single deployment folder in
    the 'output_root' directory. The deployment folder name is a combination of the provided
    'location' name and the earliest date recorded in the EXIF:CreateDate tags in the images. A set
    of folders of calibration images can also be provided, which are moved into a single CALIB
    directory within the new deployment directory.
    
    When 'copy' is False, which is the default, the image directories are scanned and validated but
    the new deployment directory is not created or populated. The new deployment directory is only
    created when 'copy' is True. Note that the function **does not delete** the source files when
    compiling the new deployment folder.
    """
    
    desc = textwrap.dedent(_process_deployment_cli.__doc__)
    fmt = argparse.RawDescriptionHelpFormatter
    parser = argparse.ArgumentParser(description=desc, formatter_class=fmt)
    
    parser.add_argument('location', type=str, 
                        help='A SAFE location code from the gazetteer that will be '
                             'used in the folder and file names.')
    parser.add_argument('output_root', type=str, 
                        help='A path to the directory where the deployment folder '
                             'is to be created.')
    parser.add_argument('directories', metavar='dir', type=str, nargs='+',
                        help='Paths for each directory to be included in the deployment folder.')
    parser.add_argument('-c', '--calib', default=None, type=str, action='append',
                        help='A path to a folder of calibration images. Can be repeated to '
                             'provide more than one folder of calibration images.')
    parser.add_argument('--copy', action='store_true',
                        help='Use to actually create the deployment rather than just validate.')

    args = parser.parse_args()

    process_deployment(image_dirs=args.directories, calib_dirs=args.calib,
                       location=args.location, output_root=args.output_root,
                       copy=args.copy)


def _extract_deployment_data_cli():

    """
    This script takes a single deployment folder and extracts EXIF data for the deployment
    into a tab delimited file. By default, the data is written to a file `exif_data.dat` 
    within the deployment directory.
    """
    
    desc = textwrap.dedent(_extract_deployment_data_cli.__doc__)
    fmt = argparse.RawDescriptionHelpFormatter
    parser = argparse.ArgumentParser(description=desc, formatter_class=fmt)
    
    parser.add_argument('deployment',
                        help='A path to a deployment directory')
    parser.add_argument('-o', '--outfile', default=None,
                        help='An output file name')

    args = parser.parse_args()

    extract_deployment_data(deployment=args.deployment, outfile=args.outfile)

