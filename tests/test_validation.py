"""Contract validation tests (M2): StructureValidator + format_version.

No database needed. Fixtures are built with the test producer
(``tests/support/orm_producer.py``) so the happy path exercises exactly
what a real producer emits, including wave-0 entities (CHECK constraints
and comments).
"""

import copy

import pytest

from asqueel_migration import FORMAT_VERSION, SqlMigrator, StructureValidator
from asqueel_migration.exceptions import SqlValidationError

from .support.orm_producer import OrmJsonProducer, SrcModel


def sample_structure():
    """A representative producer output: FK, unique, index, CHECK, comments."""
    model = SrcModel()
    pkg = model.package('alfa', sqlschema='alfa')
    author = pkg.table('author', pkey='id', comment='Authors registry')
    author.column('id', dtype='serial')
    author.column('name', size=':45', unique=True, comment='Full name')
    recipe = pkg.table('recipe', pkey='id')
    recipe.column('id', dtype='serial')
    recipe.column('title', indexed=True)
    recipe.column('author_id', dtype='L').relation('alfa.author.id',
                                                   mode='foreignkey')
    recipe.column('rating', dtype='I')
    recipe.checkConstraint('chk_recipe_rating', '(rating >= 0)')
    return OrmJsonProducer(model, 'validation_db').get_json_struct()


class TestStructureValidator:

    def test_producer_output_validates(self):
        normalized = StructureValidator().validate(sample_structure())
        assert 'root' in normalized
        assert 'format_version' not in normalized

    def test_format_version_accepted_and_stripped(self):
        structure = sample_structure()
        structure['format_version'] = FORMAT_VERSION
        normalized = StructureValidator().validate(structure)
        assert 'format_version' not in normalized

    def test_unknown_format_version_rejected(self):
        structure = sample_structure()
        structure['format_version'] = '9.9'
        with pytest.raises(SqlValidationError) as excinfo:
            StructureValidator().validate(structure)
        assert 'format_version' in str(excinfo.value)

    def test_missing_containers_are_normalized(self):
        """Older-format input (missing containers) is filled, not rejected."""
        structure = sample_structure()
        structure['root'].pop('event_triggers')
        structure['root'].pop('extensions')
        table = structure['root']['schemas']['alfa']['tables']['alfa_author']
        table.pop('indexes')
        normalized = StructureValidator().validate(structure)
        root = normalized['root']
        assert root['event_triggers'] == {}
        assert root['extensions'] == {}
        assert root['schemas']['alfa']['tables']['alfa_author']['indexes'] == {}

    def test_validate_returns_a_copy(self):
        structure = sample_structure()
        normalized = StructureValidator().validate(structure)
        normalized['root']['schemas'].clear()
        assert structure['root']['schemas']

    def test_pkey_column_must_exist(self):
        structure = sample_structure()
        table = structure['root']['schemas']['alfa']['tables']['alfa_author']
        table['attributes']['pkeys'] = 'missing_col'
        with pytest.raises(SqlValidationError) as excinfo:
            StructureValidator().validate(structure)
        assert "pkey column 'missing_col'" in str(excinfo.value)

    def test_unknown_dtype_rejected(self):
        structure = sample_structure()
        table = structure['root']['schemas']['alfa']['tables']['alfa_author']
        table['columns']['name']['attributes']['dtype'] = 'WRONG'
        with pytest.raises(SqlValidationError) as excinfo:
            StructureValidator().validate(structure)
        assert "unknown dtype 'WRONG'" in str(excinfo.value)

    def test_unknown_column_attribute_rejected(self):
        structure = sample_structure()
        table = structure['root']['schemas']['alfa']['tables']['alfa_author']
        table['columns']['name']['attributes']['name_long'] = 'Name'
        with pytest.raises(SqlValidationError) as excinfo:
            StructureValidator().validate(structure)
        assert "unknown attribute 'name_long'" in str(excinfo.value)

    def test_fk_target_must_exist(self):
        structure = sample_structure()
        recipe = structure['root']['schemas']['alfa']['tables']['alfa_recipe']
        relation = next(iter(recipe['relations'].values()))
        relation['attributes']['related_table'] = 'alfa_ghost'
        with pytest.raises(SqlValidationError) as excinfo:
            StructureValidator().validate(structure)
        assert "related_table 'alfa.alfa_ghost'" in str(excinfo.value)

    def test_fk_related_column_must_exist(self):
        structure = sample_structure()
        recipe = structure['root']['schemas']['alfa']['tables']['alfa_recipe']
        relation = next(iter(recipe['relations'].values()))
        relation['attributes']['related_columns'] = ['ghost_col']
        with pytest.raises(SqlValidationError) as excinfo:
            StructureValidator().validate(structure)
        assert "related column 'ghost_col'" in str(excinfo.value)

    def test_hashed_names_must_match_structure(self):
        structure = sample_structure()
        recipe = structure['root']['schemas']['alfa']['tables']['alfa_recipe']
        index_name, index_item = next(iter(recipe['indexes'].items()))
        index_item['entity_name'] = 'idx_deadbeef'
        recipe['indexes']['idx_deadbeef'] = recipe['indexes'].pop(index_name)
        with pytest.raises(SqlValidationError) as excinfo:
            StructureValidator().validate(structure)
        assert 'structural hash' in str(excinfo.value)

    def test_check_requires_clause(self):
        structure = sample_structure()
        recipe = structure['root']['schemas']['alfa']['tables']['alfa_recipe']
        recipe['constraints']['chk_recipe_rating']['attributes'].pop('check_clause')
        with pytest.raises(SqlValidationError) as excinfo:
            StructureValidator().validate(structure)
        assert 'check_clause' in str(excinfo.value)

    def test_all_errors_reported_together(self):
        structure = sample_structure()
        table = structure['root']['schemas']['alfa']['tables']['alfa_author']
        table['attributes']['pkeys'] = 'missing_col'
        table['columns']['name']['attributes']['dtype'] = 'WRONG'
        with pytest.raises(SqlValidationError) as excinfo:
            StructureValidator().validate(structure)
        assert len(excinfo.value.errors) >= 2


class TestFormatVersionEnvelope:
    """The migrator strips the envelope key before diffing."""

    def test_extract_orm_strips_format_version(self):
        from unittest.mock import MagicMock
        migrator = SqlMigrator(MagicMock())
        structure = sample_structure()
        structure['format_version'] = FORMAT_VERSION
        migrator.ormStructure = structure
        migrator.extractOrm()
        assert 'format_version' not in migrator.ormStructure
        assert migrator.ormStructure['root'] == structure['root']
        assert migrator.ormStructure['root'] is not structure['root']


@pytest.mark.parametrize('formal_validation', [False, True])
@pytest.mark.parametrize('value', [None, [], 'invalid'])
@pytest.mark.parametrize('path', [
    'root',
    'root.schemas',
    'root.extensions',
    'root.event_triggers',
    'root.schemas.alfa',
    'root.schemas.alfa.tables',
    'root.schemas.alfa.tables.alfa_author',
    'root.schemas.alfa.tables.alfa_author.attributes',
    'root.schemas.alfa.tables.alfa_author.columns',
    'root.schemas.alfa.tables.alfa_author.columns.id',
    'root.schemas.alfa.tables.alfa_author.columns.id.attributes',
    'root.schemas.alfa.tables.alfa_recipe.relations',
    'root.schemas.alfa.tables.alfa_recipe.constraints',
    'root.schemas.alfa.tables.alfa_recipe.indexes',
])
def test_malformed_containers_report_path_without_mutating_input(monkeypatch, formal_validation, value, path):
    from asqueel_migration import validation

    if formal_validation:
        pytest.importorskip('jsonschema')
    else:
        monkeypatch.setattr(validation, 'jsonschema', None)
    structure = sample_structure()
    keys = path.split('.')
    parent = structure
    for key in keys[:-1]:
        parent = parent[key]
    parent[keys[-1]] = value
    original = copy.deepcopy(structure)
    with pytest.raises(SqlValidationError) as error:
        StructureValidator().validate(structure)
    assert f'{path}: must be a dict' in error.value.errors
    assert structure == original


@pytest.mark.parametrize('container', ['relations', 'constraints', 'indexes'])
@pytest.mark.parametrize('bad_attributes', [False, True])
def test_malformed_leaf_entities_without_optional_validator(monkeypatch, container, bad_attributes):
    from asqueel_migration import validation

    monkeypatch.setattr(validation, 'jsonschema', None)
    structure = sample_structure()
    items = structure['root']['schemas']['alfa']['tables']['alfa_recipe'][container]
    name = next(iter(items))
    path = f'root.schemas.alfa.tables.alfa_recipe.{container}.{name}'
    if bad_attributes:
        items[name]['attributes'] = []
        path += '.attributes'
    else:
        items[name] = None
    with pytest.raises(SqlValidationError) as error:
        StructureValidator().validate(structure)
    assert f'{path}: must be a dict' in error.value.errors


def test_multiple_shape_errors_are_reported_together():
    structure = sample_structure()
    root = structure['root']
    root['extensions'] = []
    root['schemas']['alfa']['tables']['alfa_author']['columns'] = None
    with pytest.raises(SqlValidationError) as error:
        StructureValidator().validate(structure)
    assert error.value.errors == [
        'root.schemas.alfa.tables.alfa_author.columns: must be a dict',
        'root.extensions: must be a dict',
    ]


def test_older_producer_normalization_without_optional_validator(monkeypatch):
    from asqueel_migration import validation

    monkeypatch.setattr(validation, 'jsonschema', None)
    structure = sample_structure()
    del structure['root']['extensions']
    del structure['root']['event_triggers']
    original = copy.deepcopy(structure)
    normalized = StructureValidator().validate(structure)
    assert normalized['root']['extensions'] == {}
    assert normalized['root']['event_triggers'] == {}
    assert structure == original
