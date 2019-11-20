import os
import sys
import argparse
import progressbar
import shutil
import exiftool
import datetime

"""
This script rearranges a set of folders from a camera trap deployment
into a single folder and sets standardised names. It handles CALIB 
directories and also extracts exif data.

EXIF data is surprisingly annoying to read in Python. Many libraries exist
but few handle much beyond a standard set of tags, leaving a lot of information
either unread or as raw hex. The Perl Exiftool is backed by a gigantic library
of tag identifications, so the pyexiftool interface - which just calls exiftool
and wraps up the response - seems to be one of the few options to actually be 
able to leverage that information. You will need to install ExifTool and then
pip install ocrd-pyexiftool
"""


def _process_folder(image_dir, location, et, report_n=5):

    """
    This private function processes a single folder of images
    
    Args:
        image_dir: The directory to process
        location: The name of the location to be used as the deployment name
        et: An exiftool instance
        report_n: Number of files to report for missing tag data
    
    """

    sys.stdout.write(f'Processing directory: {image_dir}\n')
    
    # Load list of files, ignoring nested directories and separate JPEGS
    files =  next(os.walk(image_dir))[2]
    jpeg_files = [fl for fl in files if fl.lower().endswith('jpg')]
    other_files = set(files) - set(jpeg_files) 
    
    # report on what is found
    sys.stdout.write(f' - Found {len(jpeg_files)} JPEG files\n')

    if other_files:
        sys.stdout.write(f' - *!* Found {len(other_files)} other files: {", ".join(other_files)}\n')
    
    sys.stdout.write(' - Scanning EXIF data\n')
    sys.stdout.flush()

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


def process_deployment(image_dirs, location, output_root, calib_dirs=[], report_n=5, copy=False):

    """
    This function takes a set of directories containing camera trap images
    and rebuilds them into a single deployment directory with standardised names.
    It handles a calibration folder, which is moved inside the main directory.

    Args:
        image_dirs: A list of directories containing camera trap images
        location: The name of the location to be used as the deployment name
        output_root: The location to compile the deployment folder to
        calib: An optional list of directories of calibration images.

    Returns:
        None
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
    image_data = [_process_folder(f, location, et, report_n) for f in image_dirs]
    dates = [dat[1] for dat in image_data]
    files = [dat[0] for dat in image_data]
    files = [item for sublist in files for item in sublist]
    
    # Process calibration folders
    if calib_dirs is not None:
        calib_data = [_process_folder(f, location, et, report_n) for f in calib_dirs]
        dates += [dat[1] for dat in calib_data]
        calib_files = [dat[0] for dat in calib_data]
        calib_files = [item for sublist in calib_files for item in sublist]
        files += [(src, os.path.join('CALIB', dest)) for src, dest in calib_files]
    
    # Look for file name collisions across the whole set
    all_new_file_names = [f[1] for f in files]
    if len(all_new_file_names) > len(set(all_new_file_names)):
        raise RuntimeError('Duplication found in new image names.')
    
    if copy:
        
        # get the final directory name and check it doesn't already exist
        outdir = '{}_{}'.format(location, min(dates).strftime("%Y%m%d"))
        outdir = os.path.abspath(os.path.join(output_root, outdir))
        if os.path.exists(outdir):
            raise IOError('Output directory already exists:\n    {}'.format(outdir))
        else:
            os.mkdir(outdir)
            if calib_dirs is not None:
                os.mkdir(os.path.join(outdir, 'CALIB'))
        
        # move the files and insert the original file location into the EXIF metadata
        sys.stdout.write('Copying files:\n')
        sys.stdout.flush()
        
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


def main():

    """
    This program consolidates a set of camera trap image folders from a single
    deployment into a single folder, renaming the images to a standardised format.

    It does _not_ alter the original folders: all of the images are copied into
    a new folder. It also checks that all of the new images are getting unique names
    before starting to copy files.
    """

    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument('location', type=str, 
                        help='A SAFE location code from the gazetteer that will be '
                             'used in the folder and file names.')
    parser.add_argument('output_root', type=str, 
                        help='A path to the directory where the deployment folder '
                             'is to be created.')
    parser.add_argument('directories', metavar='dir', type=str, nargs='+',
                        help='Paths for each directory to be included in the deployment folder.')
    parser.add_argument('-c', '--calib', default=None, type=str, action='append',
                        help='A path to a folder of calibration images for the '
                             'deployment. This option can be used multiple times'
                             'to include more than one folder of calibration images.')
    parser.add_argument('--copy', action='store_true',
                        help='By default, the program runs checking and prints out '
                             'validation messages. It will only actually copy new '
                             'files into their new locations if this option is specified.')
    parser.add_argument('--report', type=int, default=5,
                        help='If key EXIF tags are missing, up to this many problem filenames '
                             'are provided to help troubleshoot.')


    args = parser.parse_args()

    process_deployment(image_dirs=args.directories, calib_dirs=args.calib,
                       location=args.location, output_root=args.output_root,
                       copy=args.copy, report_n=args.report)


if __name__ == "__main__":
    main()
