import os.path
import tarfile
import zipfile
from glob import glob


def compare_zip_files(zip1_path, zip2_path):
    files_missing_from_zip1 = []
    files_missing_from_zip2 = []

    with zipfile.ZipFile(zip1_path, "r") as zip1:
        zip1_file_list = zip1.namelist()

    with zipfile.ZipFile(zip2_path, "r") as zip2:
        zip2_file_list = zip2.namelist()

    # Remove version difference
    version = os.path.basename(zip1_path).split("-py3")[0]
    zip1_file_list = [f.replace(version, "$VERSION") for f in zip1_file_list]
    version = os.path.basename(zip2_path).split("-py3")[0]
    zip2_file_list = [f.replace(version, "$VERSION") for f in zip2_file_list]

    for file_name in zip1_file_list:
        if file_name not in zip2_file_list:
            files_missing_from_zip2.append(file_name)

    for file_name in zip2_file_list:
        if file_name not in zip1_file_list:
            files_missing_from_zip1.append(file_name)

    return files_missing_from_zip1, files_missing_from_zip2


def compare_tar_files(tar1_path, tar2_path):
    files_missing_from_tar1 = []
    files_missing_from_tar2 = []

    with tarfile.open(tar1_path, "r") as tar1:
        tar1_file_list = [member.name for member in tar1.getmembers() if member.isfile()]

    with tarfile.open(tar2_path, "r") as tar2:
        tar2_file_list = [member.name for member in tar2.getmembers() if member.isfile()]

    # Remove version difference
    version = os.path.basename(tar1_path).split(".tar")[0].split("-py_0")[0]
    tar1_file_list = [f.replace(version, "$VERSION") for f in tar1_file_list]
    version = os.path.basename(tar2_path).split(".tar")[0].split("-py_0")[0]
    tar2_file_list = [f.replace(version, "$VERSION") for f in tar2_file_list]

    for file_name in tar1_file_list:
        if file_name not in tar2_file_list:
            files_missing_from_tar2.append(file_name)

    for file_name in tar2_file_list:
        if file_name not in tar1_file_list:
            files_missing_from_tar1.append(file_name)

    return files_missing_from_tar1, files_missing_from_tar2


before_path = glob("/home/shh/Downloads/main/*.whl")[0]
after_path = glob("/home/shh/projects/holoviz/repos/holoviews/dist/*.whl")[0]

missing_from_zip1, missing_from_zip2 = compare_zip_files(before_path, after_path)

print("Files missing from main wheel:")
print(missing_from_zip1)
print("\nFiles missing from pixi wheel:")
print(missing_from_zip2)
print()

before_path = glob("/home/shh/Downloads/main/*.tar.gz")[0]
after_path = glob("/home/shh/projects/holoviz/repos/holoviews/dist/*.tar.gz")[0]

missing_from_tar1, missing_from_tar2 = compare_tar_files(before_path, after_path)

#  Filter out top-level example folder, this is a known bug
missing_from_tar2 = [f for f in missing_from_tar2 if not f.startswith("$VERSION/examples")]

print("Files missing from main sdist:")
print(missing_from_tar1)
print("\nFiles missing from pixi sdist:")
print(missing_from_tar2)
print()

before_path = glob("/home/shh/Downloads/main/*.tar.bz2")[0]
after_path = glob("/home/shh/projects/holoviz/repos/holoviews/dist/*.tar.bz2")[0]

missing_from_tar1, missing_from_tar2 = compare_tar_files(before_path, after_path)

print("Files missing from main conda:")
print(missing_from_tar1)
print("\nFiles missing from pixi conda:")
print(missing_from_tar2)
