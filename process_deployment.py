import os
import sys
import argparse
import progressbar
import shutil
import exiftool
import datetime

# pip install ocrd-pyexiftool


"""
This script rearranges a set of folders from a camera trap deployment
into a single folder and sets standardised names. It handles CALIB 
directories and also extracts exif data.

EXIF data is suprisingly annoying to read in Python. Many libraries exist
but few handle much beyond a standard set of tags, leaving a lot of information
either unread or as raw hex. The Perl Exiftool is backed by a gigantic library
of tag identifications, so the pyexiftool interface - which just calls exiftool
and wraps up the response - seems to be one of the few options to actually be 
able to leverage that information - but it isn't on pypi.

https://github.com/smarnach/pyexiftool


"""


def process_deployment(image_dirs, location, output_root, calib=None):

    """
    This function takes a set of directories containing camera trap images
    and rebuilds them into a single deployment directory with standardised names.
    It handles a calibration folder, which is moved inside the main directory.

    Args:
        image_dirs: A list of directories containing camera trap images
        location: The name of the location to be used as the deployment name
        output_root: The location to compile the deployment folder to
        calib: An optional directory of calibration images.

    Returns:

    """

    # add the calibration folder to the list of image directories to
    # get a list of directories to process
    if calib is not None:
        process_dirs = image_dirs + [calib]
    else:
        process_dirs = image_dirs

    # Check image directories exist and are directories
    dir_check = [os.path.isdir(dr) for dr in process_dirs]
    if not all(dir_check):
        missing = [dr for dr, ck in zip(process_dirs, dir_check) if not ck]
        raise IOError('Directories not found: {}'.format(', '.join(missing)))

    # load list of files and pull out jpeg files
    image_dir_contents = {dr: os.listdir(dr) for dr in process_dirs}
    image_dir_jpegs = {dr: [fl for fl in cont if fl.lower().endswith('jpg')]
                       for dr, cont in image_dir_contents.items()}

    # report on what is found
    for im_dir in process_dirs:
        n_files = len(image_dir_contents[im_dir])
        n_jpegs = len(image_dir_jpegs[im_dir])
        msg = ' - Found {} containing {} JPEG images\n'.format(im_dir, n_jpegs)
        sys.stdout.write(msg)
        if n_files != n_jpegs:
            extra = ', '.join(set(image_dir_contents[im_dir]) - set(image_dir_jpegs[im_dir]))
            msg = ' *!* {} non-image files or folders also found: {}\n'
            sys.stdout.write(msg.format(n_files - n_jpegs, extra))

    # check the output root directory
    if not os.path.isdir(output_root):
        raise IOError('Output root directory not found')

    # get an exifread.ExifTool instance
    et = exiftool.ExifTool()
    et.start()

    # track earliest date
    min_date = datetime.datetime(9999, 12, 31, 23, 59, 59)

    # dictionary to hold new names
    new_files = {}

    # now scan the files to get new names, a folder at a time
    # to keep any calib images held separately
    for path, files in image_dir_jpegs.items():

        sys.stdout.write(' - Scanning EXIF data for {}\n'.format(path))
        sys.stdout.flush()

        # get full paths
        files = [os.path.join(path, fl) for fl in files]

        # get creation date and sequence tag from EXIF
        tags = ['EXIF:CreateDate', u'MakerNotes:Sequence']
        tag_data = et.get_tags_batch(tags, files)

        # check tags found
        date_found = ['EXIF:CreateDate' in tg for tg in tag_data]
        seq_found = ['MakerNotes:Sequence' in tg for tg in tag_data]

        if not all(date_found) or not all(seq_found):
            raise RuntimeError('Files in {} missing date and/or sequence tags'.format(path))

        create_date = [datetime.datetime.strptime(td['EXIF:CreateDate'], '%Y:%m:%d %H:%M:%S')
                       for td in tag_data]

        # in burst mode, time to seconds is not unique, so add sequence number
        sequence = ['_' + td[u'MakerNotes:Sequence'].split()[0] for td in tag_data]

        # update earliest date
        if min(create_date) < min_date:
            min_date = min(create_date)

        # update the dictionaries
        image_dir_jpegs[path] = files
        new_files[path] = [location + "_" + dt.strftime("%Y%m%d_%H%M%S") + seq + ".jpg"
                           for dt, seq in zip(create_date, sequence)]

    # Look for file name collisions across the whole set
    all_new_file_names = sum(new_files.values(), [])
    if len(all_new_file_names) > len(set(all_new_file_names)):
        raise RuntimeError('Duplication found in new image names.')

    # pop the calibration folder off the current and new names
    if calib is not None:
        calib_files = image_dir_jpegs.pop(calib)
        calib_new_files = new_files.pop(calib)

    # get the final directory name and check it doesn't already exist
    outdir = '{}_{}'.format(location, min_date.strftime("%Y%m%d"))
    outdir = os.path.abspath(os.path.join(output_root, outdir))
    if os.path.exists(outdir):
        raise IOError('Output directory already exists:\n    {}'.format(outdir))
    else:
        os.mkdir(outdir)

    # move the files
    for im_dir in image_dirs:
        source = image_dir_jpegs[im_dir]
        destination = [os.path.join(outdir, fl) for fl in new_files[im_dir]]
        sys.stdout.write(' - Copying contents of {}\n'.format(im_dir))
        sys.stdout.flush()

        with progressbar.ProgressBar(max_value=len(source)) as bar:
            for idx, (src, dst) in enumerate(zip(source, destination)):
                shutil.copyfile(src, dst)
                bar.update(idx)

    # create and move the calibration folder
    if calib is not None:
        os.mkdir(os.path.join(outdir, 'calib'))
        calib_new_files = [os.path.join(outdir, 'calib', fl) for fl in calib_new_files]
        sys.stdout.write(' - Copying contents of {}\n'.format(calib))
        sys.stdout.flush()

        with progressbar.ProgressBar(max_value=len(calib_files)) as bar:
            for idx, (src, dst) in enumerate(zip(calib_files, calib_new_files)):
                shutil.copyfile(src, dst)
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
    parser.add_argument('location',
                        help='A SAFE location code from the gazetteer that will be '
                             'used in the folder and file names.')
    parser.add_argument('output_root',
                        help='A path to the directory where the deployment folder '
                             'is to be created.')
    parser.add_argument('directories', metavar='N', type=str, nargs='+',
                        help='Paths for each directory to be included in the deployment folder.')
    parser.add_argument('-c', '--calib', default=None,
                        help='A path to a folder of calibration images for the '
                             'deployment.')

    args = parser.parse_args()

    process_deployment(image_dirs=args.directories, calib=args.calib,
                       location=args.location, output_root=args.output_root)


if __name__ == "__main__":
    main()
