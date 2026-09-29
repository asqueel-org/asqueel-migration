"""Check release metadata and packaged contracts before uploading artifacts."""

import sys
import tarfile
import zipfile
from email.parser import BytesParser
from pathlib import Path

REQUIRED = ('py.typed', 'schemas/structure-1.0.json', 'schemas/sql_model-1.0.xsd')

for filename in sys.argv[1:]:
    path = Path(filename)
    if path.suffix == '.whl':
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            metadata = archive.read(next(n for n in names if n.endswith('.dist-info/METADATA')))
    else:
        with tarfile.open(path) as archive:
            names = archive.getnames()
            metadata = archive.extractfile(next(n for n in names if n.endswith('/PKG-INFO'))).read()
    for required in REQUIRED:
        assert any(('/' + n).endswith('/genro_sqlmigration/' + required) for n in names), required
    requirements = BytesParser().parsebytes(metadata).get_all('Requires-Dist', [])
    assert not any(' @ ' in r for r in requirements), 'Direct URL dependency cannot be published'
    print(f'{path.name}: metadata and packaged contracts OK')
