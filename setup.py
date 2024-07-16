from setuptools import find_packages, setup
from glob import glob

package_name = 'vr-server'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name, glob("launch/*"))
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='smartlab',
    maintainer_email='smartlab@todo.todo',
    description='TODO: Package description',
    license='TODO: License declaration',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'vr_server = vr_server.server:main'
        ],
    },
)
