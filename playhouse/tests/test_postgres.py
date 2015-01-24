#coding:utf-8
import datetime
import json
import os
import sys
import uuid

import psycopg2
try:
    from psycopg2.extras import Json
except ImportError:
    Json = None

from peewee import UUIDField
from playhouse.postgres_ext import *
from playhouse.tests.base import database_initializer
from playhouse.tests.base import ModelTestCase
from playhouse.tests.base import PeeweeTestCase
from playhouse.tests.base import skip_if


PYPY = 'PyPy' in sys.version
test_db = database_initializer.get_database(
    'postgres',
    db_class=PostgresqlExtDatabase)
test_ss_db = database_initializer.get_database(
    'postgres',
    db_class=PostgresqlExtDatabase,
    server_side_cursors=True,
    user='postgres')


class BaseModel(Model):
    class Meta:
        database = test_db

class Testing(BaseModel):
    name = CharField()
    data = HStoreField()

    class Meta:
        order_by = ('name',)

try:
    class TestingJson(BaseModel):
        data = JSONField()
except:
    TestingJson = None

try:
    class BJson(BaseModel):
        data = BinaryJSONField()
except:
    BJson = None

class TestingID(BaseModel):
    uniq = UUIDField()

class UUIDData(BaseModel):
    id = UUIDField(primary_key=True)
    data = CharField()

class UUIDRelatedModel(BaseModel):
    data = ForeignKeyField(UUIDData, null=True, related_name='related_models')
    value = IntegerField(default=0)

class TZModel(BaseModel):
    dt = DateTimeTZField()

class ArrayModel(BaseModel):
    tags = ArrayField(CharField)
    ints = ArrayField(IntegerField, dimensions=2)

class SSCursorModel(Model):
    data = CharField()

    class Meta:
        database = test_ss_db

class NormalModel(BaseModel):
    data = CharField()

class FTSModel(BaseModel):
    title = CharField()
    data = TextField()
    fts_data = TSVectorField()

MODELS = [
    Testing,
    TestingID,
    UUIDData,
    UUIDRelatedModel,
    ArrayModel,
    FTSModel,
]

class BasePostgresqlExtTestCase(ModelTestCase):
    requires = MODELS


class TestUUIDField(BasePostgresqlExtTestCase):
    def test_uuid(self):
        uuid_str = 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11'
        uuid_obj = uuid.UUID(uuid_str)

        t1 = TestingID.create(uniq=uuid_obj)
        t1_db = TestingID.get(TestingID.uniq == uuid_str)
        self.assertEqual(t1, t1_db)

        t2 = TestingID.get(TestingID.uniq == uuid_obj)
        self.assertEqual(t1, t2)

    def test_uuid_foreign_keys(self):
        data_a = UUIDData.create(id=uuid.uuid4(), data='a')
        data_b = UUIDData.create(id=uuid.uuid4(), data='b')

        rel_a1 = UUIDRelatedModel.create(data=data_a, value=1)
        rel_a2 = UUIDRelatedModel.create(data=data_a, value=2)
        rel_none = UUIDRelatedModel.create(data=None, value=3)

        db_a = UUIDData.get(UUIDData.id == data_a.id)
        self.assertEqual(db_a.id, data_a.id)
        self.assertEqual(db_a.data, 'a')

        values = [rm.value
                  for rm in db_a.related_models.order_by(UUIDRelatedModel.id)]
        self.assertEqual(values, [1, 2])

        rnone = UUIDRelatedModel.get(UUIDRelatedModel.data >> None)
        self.assertEqual(rnone.value, 3)

        ra = (UUIDRelatedModel
              .select()
              .where(UUIDRelatedModel.data == data_a)
              .order_by(UUIDRelatedModel.value.desc()))
        self.assertEqual([r.value for r in ra], [2, 1])


class TestTZField(BasePostgresqlExtTestCase):
    def test_tz_field(self):
        TZModel.drop_table(True)
        TZModel.create_table()

        test_db.execute_sql('set time zone "us/central";')

        dt = datetime.datetime.now()
        tz = TZModel.create(dt=dt)
        self.assertTrue(tz.dt.tzinfo is None)

        tz = TZModel.get(TZModel.id == tz.id)
        self.assertFalse(tz.dt.tzinfo is None)


class TestHStoreField(BasePostgresqlExtTestCase):
    def setUp(self):
        super(TestHStoreField, self).setUp()
        self.t1 = None
        self.t2 = None

    def create(self):
        self.t1 = Testing.create(name='t1', data={'k1': 'v1', 'k2': 'v2'})
        self.t2 = Testing.create(name='t2', data={'k2': 'v2', 'k3': 'v3'})

    def test_hstore_storage(self):
        self.create()
        self.assertEqual(Testing.get(name='t1').data, {'k1': 'v1', 'k2': 'v2'})
        self.assertEqual(Testing.get(name='t2').data, {'k2': 'v2', 'k3': 'v3'})

        self.t1.data = {'k4': 'v4'}
        self.t1.save()
        self.assertEqual(Testing.get(name='t1').data, {'k4': 'v4'})

        t = Testing.create(name='t3', data={})
        self.assertEqual(Testing.get(name='t3').data, {})

    def test_hstore_selecting(self):
        self.create()

        sq = Testing.select(Testing.name, Testing.data.keys().alias('keys'))
        self.assertEqual([(x.name, sorted(x.keys)) for x in sq], [
            ('t1', ['k1', 'k2']), ('t2', ['k2', 'k3'])
        ])

        sq = Testing.select(Testing.name, Testing.data.values().alias('vals'))
        self.assertEqual([(x.name, sorted(x.vals)) for x in sq], [
            ('t1', ['v1', 'v2']), ('t2', ['v2', 'v3'])
        ])

        sq = Testing.select(Testing.name, Testing.data.items().alias('mtx'))
        self.assertEqual([(x.name, sorted(x.mtx)) for x in sq], [
            ('t1', [['k1', 'v1'], ['k2', 'v2']]),
            ('t2', [['k2', 'v2'], ['k3', 'v3']]),
        ])

        sq = Testing.select(Testing.name, Testing.data.slice('k2', 'k3').alias('kz'))
        self.assertEqual([(x.name, x.kz) for x in sq], [
            ('t1', {'k2': 'v2'}),
            ('t2', {'k2': 'v2', 'k3': 'v3'}),
        ])

        sq = Testing.select(Testing.name, Testing.data.slice('k4').alias('kz'))
        self.assertEqual([(x.name, x.kz) for x in sq], [
            ('t1', {}),
            ('t2', {}),
        ])

        sq = Testing.select(Testing.name, Testing.data.exists('k3').alias('ke'))
        self.assertEqual([(x.name, x.ke) for x in sq], [
            ('t1', False),
            ('t2', True),
        ])

        sq = Testing.select(Testing.name, Testing.data.defined('k3').alias('ke'))
        self.assertEqual([(x.name, x.ke) for x in sq], [
            ('t1', False),
            ('t2', True),
        ])

        sq = Testing.select(Testing.name, Testing.data['k1'].alias('k1'))
        self.assertEqual([(x.name, x.k1) for x in sq], [
            ('t1', 'v1'),
            ('t2', None),
        ])

        sq = Testing.select(Testing.name).where(Testing.data['k1'] == 'v1')
        self.assertEqual([x.name for x in sq], ['t1'])

    def test_hstore_filtering(self):
        self.create()

        sq = Testing.select().where(Testing.data == {'k1': 'v1', 'k2': 'v2'})
        self.assertEqual([x.name for x in sq], ['t1'])

        sq = Testing.select().where(Testing.data == {'k2': 'v2'})
        self.assertEqual([x.name for x in sq], [])

        # test single key
        sq = Testing.select().where(Testing.data.contains('k3'))
        self.assertEqual([x.name for x in sq], ['t2'])

        # test list of keys
        sq = Testing.select().where(Testing.data.contains(['k2', 'k3']))
        self.assertEqual([x.name for x in sq], ['t2'])

        sq = Testing.select().where(Testing.data.contains(['k2']))
        self.assertEqual([x.name for x in sq], ['t1', 't2'])

        # test dict
        sq = Testing.select().where(Testing.data.contains({'k2': 'v2', 'k3': 'v3'}))
        self.assertEqual([x.name for x in sq], ['t2'])

        sq = Testing.select().where(Testing.data.contains({'k2': 'v2'}))
        self.assertEqual([x.name for x in sq], ['t1', 't2'])

        sq = Testing.select().where(Testing.data.contains({'k2': 'v3'}))
        self.assertEqual([x.name for x in sq], [])

        # test contains any.
        sq = Testing.select().where(Testing.data.contains_any('k3', 'kx'))
        self.assertEqual([x.name for x in sq], ['t2'])

        sq = Testing.select().where(Testing.data.contains_any('k2', 'x', 'k3'))
        self.assertEqual([x.name for x in sq], ['t1', 't2'])

        sq = Testing.select().where(Testing.data.contains_any('x', 'kx', 'y'))
        self.assertEqual([x.name for x in sq], [])

    def test_hstore_filter_functions(self):
        self.create()

        sq = Testing.select().where(Testing.data.exists('k2') == True)
        self.assertEqual([x.name for x in sq], ['t1', 't2'])

        sq = Testing.select().where(Testing.data.exists('k3') == True)
        self.assertEqual([x.name for x in sq], ['t2'])

        sq = Testing.select().where(Testing.data.defined('k2') == True)
        self.assertEqual([x.name for x in sq], ['t1', 't2'])

        sq = Testing.select().where(Testing.data.defined('k3') == True)
        self.assertEqual([x.name for x in sq], ['t2'])

    def test_hstore_update_functions(self):
        self.create()

        rc = Testing.update(data=Testing.data.update(k4='v4')).where(
            Testing.name == 't1'
        ).execute()
        self.assertEqual(rc, 1)
        self.assertEqual(Testing.get(name='t1').data, {'k1': 'v1', 'k2': 'v2', 'k4': 'v4'})

        rc = Testing.update(data=Testing.data.update(k5='v5', k6='v6')).where(
            Testing.name == 't2'
        ).execute()
        self.assertEqual(rc, 1)
        self.assertEqual(Testing.get(name='t2').data, {'k2': 'v2', 'k3': 'v3', 'k5': 'v5', 'k6': 'v6'})

        rc = Testing.update(data=Testing.data.update(k2='vxxx')).execute()
        self.assertEqual(rc, 2)
        self.assertEqual([x.data for x in Testing.select()], [
            {'k1': 'v1', 'k2': 'vxxx', 'k4': 'v4'},
            {'k2': 'vxxx', 'k3': 'v3', 'k5': 'v5', 'k6': 'v6'}
        ])

        rc = Testing.update(data=Testing.data.delete('k4')).where(
            Testing.name == 't1'
        ).execute()
        self.assertEqual(rc, 1)
        self.assertEqual(Testing.get(name='t1').data, {'k1': 'v1', 'k2': 'vxxx'})

        rc = Testing.update(data=Testing.data.delete('k5')).execute()
        self.assertEqual(rc, 2)
        self.assertEqual([x.data for x in Testing.select()], [
            {'k1': 'v1', 'k2': 'vxxx'},
            {'k2': 'vxxx', 'k3': 'v3', 'k6': 'v6'}
        ])

        rc = Testing.update(data=Testing.data.delete('k1', 'k2')).execute()
        self.assertEqual(rc, 2)
        self.assertEqual([x.data for x in Testing.select()], [
            {},
            {'k3': 'v3', 'k6': 'v6'}
        ])


class TestArrayField(BasePostgresqlExtTestCase):
    def _create_am(self):
        return ArrayModel.create(
            tags=['alpha', 'beta', 'gamma', 'delta'],
            ints=[[1, 2], [3, 4], [5, 6]])

    def test_array_storage_retrieval(self):
        am = self._create_am()
        am_db = ArrayModel.get(ArrayModel.id == am.id)
        self.assertEqual(am_db.tags, ['alpha', 'beta', 'gamma', 'delta'])
        self.assertEqual(am_db.ints, [[1, 2], [3, 4], [5, 6]])

    def test_array_search(self):
        def assertAM(where, *instances):
            query = (ArrayModel
                     .select()
                     .where(where)
                     .order_by(ArrayModel.id))
            self.assertEqual([x.id for x in query], [x.id for x in instances])

        am = self._create_am()
        am2 = ArrayModel.create(tags=['alpha', 'beta'], ints=[[1, 1]])
        am3 = ArrayModel.create(tags=['delta'], ints=[[3, 4]])
        am4 = ArrayModel.create(tags=['中文'], ints=[[3, 4]])
        am5 = ArrayModel.create(tags=['中文', '汉语'], ints=[[3, 4]])

        assertAM((Param('beta') == fn.Any(ArrayModel.tags)), am, am2)
        assertAM((Param('delta') == fn.Any(ArrayModel.tags)), am, am3)
        assertAM((Param('omega') == fn.Any(ArrayModel.tags)))

        # Check the contains operator.
        assertAM(SQL("tags @> ARRAY['beta']::varchar[]"), am, am2)

        # Use the nicer API.
        assertAM(ArrayModel.tags.contains('beta'), am, am2)
        assertAM(ArrayModel.tags.contains('omega', 'delta'))
        assertAM(ArrayModel.tags.contains('汉语'), am5)
        assertAM(ArrayModel.tags.contains('alpha', 'delta'), am)

        # Check for any.
        assertAM(ArrayModel.tags.contains_any('beta'), am, am2)
        assertAM(ArrayModel.tags.contains_any('中文'), am4, am5)
        assertAM(ArrayModel.tags.contains_any('omega', 'delta'), am, am3)
        assertAM(ArrayModel.tags.contains_any('alpha', 'delta'), am, am2, am3)

    def test_array_index_slice(self):
        self._create_am()
        res = (ArrayModel
               .select(ArrayModel.tags[1].alias('arrtags'))
               .dicts()
               .get())
        self.assertEqual(res['arrtags'], 'beta')

        res = (ArrayModel
               .select(ArrayModel.tags[2:4].alias('foo'))
               .dicts()
               .get())
        self.assertEqual(res['foo'], ['gamma', 'delta'])

        res = (ArrayModel
               .select(ArrayModel.ints[1][1].alias('ints'))
               .dicts()
               .get())
        self.assertEqual(res['ints'], 4)

        res = (ArrayModel
               .select(ArrayModel.ints[1:2][0].alias('ints'))
               .dicts()
               .get())
        self.assertEqual(res['ints'], [[3], [5]])


class TestTSVectorField(BasePostgresqlExtTestCase):
    messages = [
        'A faith is a necessity to a man. Woe to him who believes in nothing.',
        'All who call on God in true faith, earnestly from the heart, will '
        'certainly be heard, and will receive what they have asked and desired.',
        'Be faithful in small things because it is in them that your strength lies.',
        'Faith consists in believing when it is beyond the power of reason to believe.',
        'Faith has to do with things that are not seen and hope with things that are not at hand.',
    ]

    def setUp(self):
        super(TestTSVectorField, self).setUp()
        for idx, msg in enumerate(self.messages):
            FTSModel.create(
                title=str(idx),
                data=msg,
                fts_data=fn.to_tsvector(msg))

    def assertMessages(self, expr, expected):
        query = FTSModel.select().where(expr).order_by(FTSModel.id)
        titles = [row.title for row in query]
        self.assertEqual(list(map(int, titles)), expected)

    def test_sql(self):
        query = FTSModel.select().where(Match(FTSModel.data, 'foo bar'))
        self.assertEqual(query.sql(), (
            'SELECT "t1"."id", "t1"."title", "t1"."data", "t1"."fts_data" '
            'FROM "ftsmodel" AS t1 '
            'WHERE (to_tsvector("t1"."data") @@ to_tsquery(%s))',
            ['foo bar']
        ))

    def test_match_function(self):
        self.assertMessages(Match(FTSModel.data, 'heart'), [1])
        self.assertMessages(Match(FTSModel.data, 'god'), [1])
        self.assertMessages(Match(FTSModel.data, 'faith'), [0, 1, 2, 3, 4])
        self.assertMessages(Match(FTSModel.data, 'thing'), [2, 4])
        self.assertMessages(Match(FTSModel.data, 'faith & things'), [2, 4])
        self.assertMessages(Match(FTSModel.data, 'god | things'), [1, 2, 4])
        self.assertMessages(Match(FTSModel.data, 'god & things'), [])

    def test_tsvector_field(self):
        self.assertMessages(FTSModel.fts_data.match('heart'), [1])
        self.assertMessages(FTSModel.fts_data.match('god'), [1])
        self.assertMessages(FTSModel.fts_data.match('faith'), [0, 1, 2, 3, 4])
        self.assertMessages(FTSModel.fts_data.match('thing'), [2, 4])
        self.assertMessages(FTSModel.fts_data.match('faith & things'), [2, 4])
        self.assertMessages(FTSModel.fts_data.match('god | things'), [1, 2, 4])
        self.assertMessages(FTSModel.fts_data.match('god & things'), [])


class SSCursorTestCase(PeeweeTestCase):
    counter = 0

    def setUp(self):
        super(SSCursorTestCase, self).setUp()
        self.close_conn()  # Close open connection.
        SSCursorModel.drop_table(True)
        NormalModel.drop_table(True)
        SSCursorModel.create_table()
        NormalModel.create_table()
        self.counter = 0
        for i in range(3):
            self.create()
        if PYPY:
            self.ExceptionClass = psycopg2.OperationalError
        else:
            self.ExceptionClass = psycopg2.ProgrammingError

    def create(self):
        self.counter += 1
        SSCursorModel.create(data=self.counter)
        NormalModel.create(data=self.counter)

    def close_conn(self):
        if not test_ss_db.is_closed():
            test_ss_db.close()

    def assertList(self, iterable):
        self.assertEqual(
            [x.data for x in iterable],
            [str(i) for i in range(1, self.counter + 1)])

    def test_model_interaction(self):
        query = SSCursorModel.select().order_by(SSCursorModel.data)
        self.assertList(query)

        query2 = query.clone()
        qr = query2.execute()
        self.assertList(qr)

        # The cursor is named and is still "alive" because we can still try
        # to fetch results.
        self.assertTrue(qr.cursor.name is not None)
        self.assertEqual(qr.cursor.fetchone(), None)

        # Execute the query in a transaction.
        with test_ss_db.transaction():
            query3 = query.clone()
            qr2 = query3.execute()

            # Different named cursor
            self.assertFalse(qr2.cursor.name == qr.cursor.name)
            self.assertList(qr2)

        # After the transaction we cannot fetch a result because the cursor
        # is dead.
        self.assertRaises(self.ExceptionClass, qr2.cursor.fetchone)

        # Try using the helper.
        query4 = query.clone()
        self.assertList(ServerSide(query4))

        # Named cursor is dead.
        self.assertRaises(self.ExceptionClass, query4._qr.cursor.fetchone)

    def test_serverside_normal_model(self):
        query = NormalModel.select().order_by(NormalModel.data)
        self.assertList(query)

        # The cursor is closed.
        self.assertTrue(query._qr.cursor.closed)

        clone = query.clone()
        self.assertList(ServerSide(clone))

        # Named cursor is dead.
        self.assertRaises(self.ExceptionClass, clone._qr.cursor.fetchone)

        # Ensure where clause is preserved.
        query = query.where(NormalModel.data == '2')
        data = [x.data for x in ServerSide(query)]
        self.assertEqual(data, ['2'])

        # The cursor is open.
        self.assertFalse(query._qr.cursor.closed)

    def test_ss_cursor(self):
        tbl = SSCursorModel._meta.db_table
        name = str(uuid.uuid1())

        # Get a named cursor and execute a select query.
        cursor = test_ss_db.get_cursor(name=name)
        cursor.execute('select data from %s order by id' % tbl)

        # Ensure the cursor attributes are as we expect.
        self.assertEqual(cursor.description, None)
        self.assertEqual(cursor.name, name)
        self.assertFalse(cursor.withhold)  # Close cursor after commit.

        # Cursor works and populates description after fetching one row.
        self.assertEqual(cursor.fetchone(), ('1',))
        self.assertEqual(cursor.description[0].name, 'data')

        # Explicitly close the cursor.
        test_ss_db.commit()
        self.assertRaises(self.ExceptionClass, cursor.fetchone)

        # This would not work is the named cursor was still holding a ref to
        # the table.
        test_ss_db.execute_sql('truncate table %s;' % tbl)
        test_ss_db.commit()


class BaseJsonFieldTestCase(object):
    ModelClass = None  # Subclasses must define this.

    def test_json_field(self):
        data = {'k1': ['a1', 'a2'], 'k2': {'k3': 'v3'}}
        j = self.ModelClass.create(data=data)
        j_db = self.ModelClass.get(j._pk_expr())
        self.assertEqual(j_db.data, data)

    def test_json_lookup_methods(self):
        data = {
            'gp1': {
                'p1': {'c1': 'foo'},
                'p2': {'c2': 'bar'},
            },
            'gp2': {}}
        j = self.ModelClass.create(data=data)

        def assertLookup(lookup, expected):
            query = (self.ModelClass
                     .select(lookup)
                     .where(j._pk_expr())
                     .dicts())
            self.assertEqual(query.get(), expected)

        expr = self.ModelClass.data['gp1']['p1'].alias('pdata')
        assertLookup(expr, {'pdata': '{"c1": "foo"}'})
        assertLookup(expr.as_json(), {'pdata': {'c1': 'foo'}})

        expr = self.ModelClass.data['gp1']['p1']['c1'].alias('cdata')
        assertLookup(expr, {'cdata': 'foo'})
        assertLookup(expr.as_json(), {'cdata': 'foo'})

        j.data = [
            {'i1': ['foo', 'bar', 'baze']},
            ['nugget', 'mickey']]
        j.save()

        expr = self.ModelClass.data[0]['i1'].alias('idata')
        assertLookup(expr, {'idata': '["foo", "bar", "baze"]'})
        assertLookup(expr.as_json(), {'idata': ['foo', 'bar', 'baze']})

        expr = self.ModelClass.data[1][1].alias('ldata')
        assertLookup(expr, {'ldata': 'mickey'})
        assertLookup(expr.as_json(), {'ldata': 'mickey'})

    def test_json_path(self):
        data = {
            'foo': {
                'baz': {
                    'bar': ['i1', 'i2', 'i3'],
                    'baze': ['j1', 'j2'],
                }}}
        j = self.ModelClass.create(data=data)

        def assertPath(path, expected):
            query = (self.ModelClass
                     .select(path)
                     .where(j._pk_expr())
                     .dicts())
            self.assertEqual(query.get(), expected)

        expr = self.ModelClass.data.path('foo', 'baz', 'bar').alias('p')
        assertPath(expr, {'p': '["i1", "i2", "i3"]'})
        assertPath(expr.as_json(), {'p': ['i1', 'i2', 'i3']})

        expr = self.ModelClass.data.path('foo', 'baz', 'baze', 1).alias('p')
        assertPath(expr, {'p': 'j2'})
        assertPath(expr.as_json(), {'p': 'j2'})

    def test_json_field_sql(self):
        j = (self.ModelClass
             .select()
             .where(self.ModelClass.data == {'foo': 'bar'}))
        sql, params = j.sql()
        self.assertEqual(sql, (
            'SELECT "t1"."id", "t1"."data" '
            'FROM "%s" AS t1 WHERE ("t1"."data" = %%s)')
            % self.ModelClass._meta.db_table)
        self.assertEqual(params[0].adapted, {'foo': 'bar'})

        j = (self.ModelClass
             .select()
             .where(self.ModelClass.data['foo'] == 'bar'))
        sql, params = j.sql()
        self.assertEqual(sql, (
            'SELECT "t1"."id", "t1"."data" '
            'FROM "%s" AS t1 WHERE ("t1"."data"->>%%s = %%s)')
            % self.ModelClass._meta.db_table)
        self.assertEqual(params, ['foo', 'bar'])

    def assertItems(self, where, *items):
        query = (self.ModelClass
                 .select()
                 .where(where)
                 .order_by(self.ModelClass.id))
        self.assertEqual(
            [item.id for item in query],
            [item.id for item in items])

    def test_lookup(self):
        t1 = self.ModelClass.create(data={'k1': 'v1', 'k2': {'k3': 'v3'}})
        t2 = self.ModelClass.create(data={'k1': 'x1', 'k2': {'k3': 'x3'}})
        t3 = self.ModelClass.create(data={'k1': 'v1', 'j2': {'j3': 'v3'}})
        self.assertItems((self.ModelClass.data['k2']['k3'] == 'v3'), t1)
        self.assertItems((self.ModelClass.data['k1'] == 'v1'), t1, t3)

        # Valid key, no matching value.
        self.assertItems((self.ModelClass.data['k2'] == 'v1'))

        # Non-existent key.
        self.assertItems((self.ModelClass.data['not-here'] == 'v1'))

        # Non-existent nested key.
        self.assertItems((self.ModelClass.data['not-here']['xxx'] == 'v1'))

        self.assertItems((self.ModelClass.data['k2']['xxx'] == 'v1'))

def json_ok():
    if TestingJson is None:
        return False
    conn = test_db.get_conn()
    return conn.server_version >= 90300

@skip_if(lambda: not json_ok())
class TestJsonField(BaseJsonFieldTestCase, ModelTestCase):
    ModelClass = TestingJson
    requires = [TestingJson]

def jsonb_ok():
    if BJson is None:
        return False
    conn = test_db.get_conn()
    return conn.server_version >= 90400

@skip_if(lambda: not json_ok())
class TestBinaryJsonField(BaseJsonFieldTestCase, ModelTestCase):
    ModelClass = BJson
    requires = [BJson]

    def test_equality(self):
        data = {'k1': ['a1', 'a2'], 'k2': {'k3': 'v3'}}
        j = BJson.create(data=data)
        j_db = BJson.get(BJson.data == data)
        self.assertEqual(j.id, j_db.id)

    def _create_test_data(self):
        data = [
            {'k1': 'v1', 'k2': 'v2', 'k3': {'k4': ['i1', 'i2'], 'k5': {}}},
            ['a1', 'a2', {'a3': 'a4'}],
            {'a1': 'x1', 'a2': 'x2', 'k4': ['i1', 'i2']},
            range(10),
            range(5, 15),
            ['k4', 'k1']]

        bjson_objs = []
        for json_value in data:
            bjson_objs.append(BJson.create(data=json_value))

        return bjson_objs

    def assertBJsonObjects(self, expr, objects, indexes):
        query = (BJson
                 .select()
                 .where(expr)
                 .order_by(BJson.id))
        self.assertEqual(
            [bjson.data for bjson in query],
            [objects[index].data for index in indexes])

    def test_subscript_contains(self):
        bjson_objects = self._create_test_data()
        def assertObjects(expr, *expected):
            return self.assertBJsonObjects(expr, bjson_objects, expected)

        # 'k3' is mapped to another dictioary {'k4': [...]}. Therefore,
        # 'k3' is said to contain 'k4', but *not* ['k4'] or ['k4', 'k5'].
        assertObjects(BJson.data['k3'].contains('k4'), 0)
        assertObjects(BJson.data['k3'].contains(['k4']))
        assertObjects(BJson.data['k3'].contains(['k4', 'k5']))

        # We can check for the keys this way, though.
        assertObjects(BJson.data['k3'].contains_all('k4', 'k5'), 0)
        assertObjects(BJson.data['k3'].contains_any('k4', 'kx'), 0)

        # However, in test object index=2, 'k4' can be said to contain
        # both 'i1' and ['i1'].
        assertObjects(BJson.data['k4'].contains('i1'), 2)
        assertObjects(BJson.data['k4'].contains(['i1']), 2)

        # Interestingly, we can also specify the list of contained values
        # out-of-order.
        assertObjects(BJson.data['k4'].contains(['i2', 'i1']), 2)

        # We can test whether an object contains another JSON object fragment.
        assertObjects(BJson.data['k3'].contains({'k4': ['i1']}), 0)
        assertObjects(BJson.data['k3'].contains({'k4': ['i1', 'i2']}), 0)

        # Check multiple levels of nesting / containment.
        assertObjects(BJson.data['k3']['k4'].contains('i2'), 0)
        assertObjects(BJson.data['k3']['k4'].contains_all('i1', 'i2'), 0)
        assertObjects(BJson.data['k3']['k4'].contains_all('i0', 'i2'))
        assertObjects(BJson.data['k4'].contains_all('i1', 'i2'), 2)

        # Check array indexes.
        assertObjects(BJson.data[2].contains('a3'), 1)
        assertObjects(BJson.data[0].contains('a1'), 1)
        assertObjects(BJson.data[0].contains('k1'))

    def test_contains(self):
        bjson_objects = self._create_test_data()
        def assertObjects(expr, *expected):
            return self.assertBJsonObjects(expr, bjson_objects, expected)

        # Test for keys. 'k4' is both an object key and an array element.
        assertObjects(BJson.data.contains('k4'), 2, 5)
        assertObjects(BJson.data.contains('a1'), 1, 2)
        assertObjects(BJson.data.contains('k3'), 0)

        # We can test for multiple top-level keys/indexes.
        assertObjects(BJson.data.contains_all('a1', 'a2'), 1, 2)

        # If we test for both with .contains(), though, it is treated as
        # an object match.
        assertObjects(BJson.data.contains(['a1', 'a2']), 1)

        # Check numbers.
        assertObjects(BJson.data.contains([2, 5, 6, 7, 8]), 3)
        assertObjects(BJson.data.contains([5, 6, 7, 8, 9]), 3, 4)

        # We can check for partial objects.
        assertObjects(BJson.data.contains({'a1': 'x1'}), 2)
        assertObjects(BJson.data.contains({'k3': {'k4': []}}), 0)
        assertObjects(BJson.data.contains([{'a3': 'a4'}]), 1)

        # Check for simple keys.
        assertObjects(BJson.data.contains('a1'), 1, 2)
        assertObjects(BJson.data.contains('k3'), 0)

        # Contains any.
        assertObjects(BJson.data.contains_any('a1', 'k1'), 0, 1, 2, 5)
        assertObjects(BJson.data.contains_any('k4', 'xx', 'yy', '2'), 2, 5)
        assertObjects(BJson.data.contains_any('i1', 'i2', 'a3'))

        # Contains all.
        assertObjects(BJson.data.contains_all('k1', 'k2', 'k3'), 0)
        assertObjects(BJson.data.contains_all('k1', 'k2', 'k3', 'k4'))

    def test_integer_index_weirdness(self):
        self._create_test_data()

        def fails():
            with test_db.transaction():
                results = list(BJson.select().where(
                    BJson.data.contains_any(2, 8, 12)))

        self.assertRaises(ProgrammingError, fails)
