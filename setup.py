from setuptools import setup
from os import path

this_directory = path.abspath(path.dirname(__file__))
with open(path.join(this_directory, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

setup(name='safe_camera_trap_tools',
      version='0.8.0',
      description='Functions to help compile images and then extract data from camera trap deployments',
      long_description=long_description,
      long_description_content_type='text/markdown',
      url='https://github.com/ImperialCollegeLondon/safe_camera_trap_tools',
      author='David Orme',
      author_email='d.orme@imperial.ac.uk',
      license='MIT',
      py_modules=['safe_camera_trap_tools'],
      package_data={'safe_camera_trap_tools': ['test/*']},
      entry_points = {
              'console_scripts':
               ['process_deployment=safe_camera_trap_tools:_process_deployment_cli',
                'extract_exif_data=safe_camera_trap_tools:_extract_exif_data_cli']
      },
      zip_safe=False)
