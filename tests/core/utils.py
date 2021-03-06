# First Party
from smdebug.core.collection import Collection
from smdebug.core.collection_manager import CollectionManager
from smdebug.core.config_constants import DEFAULT_COLLECTIONS_FILE_NAME


def write_dummy_collection_file(trial):
    cm = CollectionManager()
    cm.create_collection("default")
    cm.add(Collection(trial))
    cm.export(trial, DEFAULT_COLLECTIONS_FILE_NAME)
