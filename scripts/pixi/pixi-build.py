import tarfile
import zipfile

from _artifact import download_files


def zip_files(zip_path):
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_file_list = zip_ref.namelist()
    version = zip_path.name.split("-py3")[0]
    return {f.replace(version, "$VERSION") for f in zip_file_list}


def tar_files(tar_path):
    with tarfile.open(tar_path, "r") as tar_ref:
        tar_file_list = [member.name for member in tar_ref.getmembers() if member.isfile()]
    version = tar_path.name.split(".tar")[0].split("-py_0")[0]
    return {f.replace(version, "$VERSION") for f in tar_file_list}


def compare_zip_files(zip1_path, zip2_path):
    zip1 = zip_files(zip1_path)
    zip2 = zip_files(zip2_path)
    zip1_missing = sorted(zip1 - zip2)
    zip2_missing = sorted(zip2 - zip1)
    return zip1_missing, zip2_missing


def compare_tar_files(tar1_path, tar2_path):
    tar1 = tar_files(tar1_path)
    tar2 = tar_files(tar2_path)
    tar1_missing = sorted(tar1 - tar2)
    tar2_missing = sorted(tar2 - tar1)
    return tar1_missing, tar2_missing


good_run, bad_run, good_path, bad_path = download_files(
    "holoviews", 235, 246, "build.yaml", artifact_names=["pip", "conda"]
)

before_path = next(good_path.glob("*.whl"))
after_path = next(bad_path.glob("*.whl"))
missing_from_zip1, missing_from_zip2 = compare_zip_files(before_path, after_path)

print("Files missing from main wheel:")
print(missing_from_zip1)
print("\nFiles missing from pixi wheel:")
print(missing_from_zip2)
print()

before_path = next(good_path.glob("*.tar.gz"))
after_path = next(bad_path.glob("*.tar.gz"))

missing_from_tar1, missing_from_tar2 = compare_tar_files(before_path, after_path)

#  Filter out top-level example folder, this is a known bug
missing_from_tar1 = [f for f in missing_from_tar1 if not f.startswith("$VERSION/examples")]
missing_from_tar2 = [f for f in missing_from_tar2 if not f.startswith("$VERSION/examples")]

print("Files missing from main sdist:")
print(missing_from_tar1)
print("\nFiles missing from pixi sdist:")
print(missing_from_tar2)
print()

before_path = next(good_path.glob("*.tar.bz2"))
after_path = next(bad_path.glob("*.tar.bz2"))

print("Files missing from main conda:")
print(missing_from_tar1)
print("\nFiles missing from pixi conda:")
print(missing_from_tar2)
