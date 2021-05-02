import json
from enum import Enum
from pathlib import Path
import psycopg2

conn = psycopg2.connect("dbname=ozee user=ozee password=ozee")

missing = object()

def plural(name):
    # super simple pluralization
    if name.endswith("s"):
        return f"{name}es"
    elif name.endswith("y"):
        return f"{name[:-1]}ies"
    return f"{name}s"

class Model:
    def __init_subclass__(subclass):
        subclass._table_name = subclass.__name__.lower()  # FIXME CamelCase etc. ABCFoo
        fields = {}
        for field, value in vars(subclass).items():
            if field == "id":
                raise RuntimeError("Can't explicitly define an 'id' field")
            if isinstance(value, Field):
                fields[field] = value
                if issubclass(value._type, Model):
                    value._type.install_inverse(subclass, field, value)
        fields["id"] = Field(int, required=True)
        fields["id"].__set_name__(subclass, "id")
        setattr(subclass, "id", fields["id"])
        subclass._fields = fields
        subclass.ensure_db_state()

    def __init__(self, **kwargs):
        self._initializing = True
        self._values = {}
        self._dirty = False
        for k, v in kwargs.items():
            assert k in self._fields, f"{k} is not in fields of {self}, only {self._fields}"
            setattr(self, k, v)
        for k, v in self._fields.items():
            if v._options.get("required") and k != "id" and not v._options.get("virtual"):
                assert k in kwargs, (k, kwargs, v._options.get("required"))
        self._initializing = False

    @classmethod
    def install_inverse(cls, other_model, field_name, field):
        """Set up a fake field on the other side of a foreign key relation."""
        inverse_name = field._options.get("inverse", plural(other_model._table_name))
        cls._fields[inverse_name] = Field(other_model, virtual=True, forward_name=field_name)
        cls._fields[inverse_name].__set_name__(cls, inverse_name)
        setattr(cls, inverse_name, cls._fields[inverse_name])

    def __repr__(self):
        value_list = " ".join(
            f"{k}={v!r}" for k, v in self._values.items()
        )
        return f"<{self.__class__.__name__}{'[D]' if self._dirty else ''} {value_list}>"


    @classmethod
    def drop(cls):
        sql = f"""
        DROP TABLE IF EXISTS
            {cls._table_name}
        CASCADE
        """
        with conn.cursor() as cur:
            cur.execute(sql)
            conn.commit()

    @classmethod
    def ensure_db_state(cls):
        new_state = cls.get_state()
        state_path = (Path("db_state") / cls._table_name).with_suffix(".json")
        if state_path.exists():
            with state_path.open() as f:
                old_state = json.load(f)
            if old_state == new_state:
                return  # nothing to do
            print(f"DB state: changes detected in {cls._table_name}, auto-migrating...")
            cls.migrate(old_state, new_state)
        else:
            print(f"DB state: table {cls._table_name} missing, creating...")
            cls.drop()
            cls.create()
        state_path.parent.mkdir(exist_ok=True)
        with state_path.open("w") as f:
            json.dump(new_state, f)


    @classmethod
    def get_state(cls):
        return {
            "fields": {
                name: {
                    "type": field._sql_type,
                    "options": field._options,
                }
                for name, field in cls._fields.items()
                if not field._options.get("virtual")
            },
            "foreign_keys": {
                name: field._type._table_name
                for name, field in cls._fields.items()
                if issubclass(field._type, Model) and not field._options.get("virtual")
            },
        }

    @classmethod
    def create(cls):
        state = cls.get_state()

        sql = f"""
        CREATE TABLE IF NOT EXISTS
            {cls._table_name}
        ({', '.join(name + " " + values["type"] for name, values in state["fields"].items())})
        """
        with conn.cursor() as cur:
            cur.execute(sql)
            for fk_name, fk_foreign in state["foreign_keys"].items():
                sql = f"""
                ALTER TABLE {cls._table_name} DROP CONSTRAINT IF EXISTS fk_{fk_name};
                ALTER TABLE {cls._table_name} ADD CONSTRAINT fk_{fk_name} FOREIGN KEY ({fk_name}) REFERENCES {fk_foreign}(id);
                """
                cur.execute(sql)
            conn.commit()
        print(f"DB state: created table {cls._table_name}")

    @classmethod
    def migrate(cls, old_state, new_state):
        instructions = []
        # TODO: detect renamed fields, etc.
        table = cls._table_name
        for field in {*old_state["fields"], *new_state["fields"]}:
            if field not in new_state["fields"]:
                print(f" -> dropping old field {field}")
                instructions.append(f"ALTER TABLE {table} DROP COLUMN {field};")
            if field not in old_state["fields"]:
                print(f" -> adding new field {field}")
                instructions.append(f"ALTER TABLE {table} ADD COLUMN {field} {new_state['fields'][field]['type']};")
                if field in new_state["foreign_keys"]:
                    print(" -> installing foreign key relation of", field, "=>", new_state["foreign_keys"][field])
                    instructions.append(f"""
                        ALTER TABLE {table} DROP CONSTRAINT IF EXISTS fk_{field};
                        ALTER TABLE {table} ADD CONSTRAINT fk_{field} FOREIGN KEY ({field}) REFERENCES {new_state['foreign_keys'][field]}(id);
                        """
                    )
        with conn.cursor() as cur:
            cur.execute("\n".join(instructions))
            conn.commit()


    @classmethod
    def get(cls, id):
        # return instance from database or cache
        columns = {column: value for column, value in cls._fields.items() if not value._options.get("virtual")}
        sql = f"""
        SELECT {",".join(columns)}
        FROM {cls._table_name}
        WHERE id=%s
        """
        with conn.cursor() as cur:
            cur.execute(sql, (id,))
            values = cur.fetchone()
        instance = cls(**{column: columns[column].from_sql(value) for column, value in zip(columns, values)})
        instance._dirty = False
        return instance

    def save(self):
        if not self._dirty:
            return
        if self.id:
            assignments = [
                f"{key}=%s"
                for key in self._fields
                if key != "id" and self._values.get(key, missing) is not missing
                and not self._fields[key]._options("virtual")
            ]
            sql = f"""
            UPDATE {self._table_name}
            SET {",".join(assignments)}
            WHERE id = %s;
            """
            with conn.cursor() as cur:
                cur.execute(sql, [
                    *(
                        v.to_sql(self._values[k])
                        for (k, v) in self._fields.items()
                        if k != "id" and self._values.get(k, missing) is not missing
                        and not v._options.get("virtual")
                    ),
                    self.id,
                ])
                conn.commit()
        else:
            columns, values = [], []
            for k, v in self._fields.items():
                if k == "id" or v._options.get("virtual"):
                    continue
                columns.append(k)
                default = v._options.get("default", missing)
                value = self._values.get(k, missing)
                if value is not missing:
                    values.append(v.to_sql(value))
                elif default is not missing:
                    values.append(v.to_sql(default))
                else:
                    raise ValueError(f"No value for {k} set and no default present")
            sql = f"""
            INSERT INTO
                {self._table_name}
                ({",".join(columns)})
            VALUES
                ({",".join(["%s"]*len(values))})
            RETURNING
                id;
            """
            with conn.cursor() as cur:
                cur.execute(sql, values)
                self._values["id"] = cur.fetchone()[0]  # skip Field.__set__
                conn.commit()
        self._dirty = False

    @classmethod
    def select(cls, **kwargs):
        return RecordSet(cls, **kwargs)


class RecordSet:
    def __init__(self, model_class, where=None, limit=None, order_by=None):
        self.model_class = model_class
        self.where = where
        self.limit = limit
        self.order_by = order_by

    def __repr__(self):
        return f"<RecordSet({self.model_class.__name__}) {self.where if self.where else ''}>"

    def _resolve_where(self):
        if self.where:
            where_sql, literals, joins = self.where.to_sql()
            join_expression = "\n".join(
                "JOIN {foreign} ON {foreign}.{foreign_column} = {source}.{source_column}".format(
                    foreign=foreign,
                    source=source,
                    foreign_column=foreign_column,
                    source_column=source_column,
                ) for source, foreign, source_column, foreign_column in joins
            )
            return f"WHERE {where_sql}", join_expression, literals
        else:
            return "", "", []

    def __iter__(self):
        where_expression, join_expression, literals = self._resolve_where()

        limit_expression = f"LIMIT {int(self.limit)}" if self.limit else ""
        if isinstance(self.order_by, tuple):
            order_by = f"{', '.join(self.order_by)}"
        order_by_expression = f"ORDER BY {self.order_by}" if self.order_by else ""

        sql = f"""
        SELECT
            {self.model_class._table_name}.id
        FROM
            {self.model_class._table_name}
        {join_expression}
        {where_expression}
        {order_by_expression}
        {limit_expression}
        """
        with conn.cursor() as cur:
            cur.execute(sql, literals)
            for row in cur.fetchall():
                yield self.model_class.get(row[0])

    def filter(self, where_expr):
        assert isinstance(where_expr, Expression)
        if not self.where:
            new_where = where_expr
        else:
            new_where = Expression("AND", [self.where, where_expr])
        return type(self)(
            self.model_class,
            limit=self.limit,
            order_by=self.order_by,
            where=new_where,
        )

    def delete(self):
        where_expression, join_expression, literals = self._resolve_where()
        sql = f"""
        DELETE
        FROM
            {self.model_class._table_name}
        {join_expression}
        {where_expression}
        """
        with conn.cursor() as cur:
            cur.execute(sql, literals)
            conn.commit()

    def update(self, **kwargs):
        # convert via self.model_class._fields -> to_sql
        where_expression, join_expression, literals = self._resolve_where()

        assert "id" not in kwargs

        assignments = [
            f"{self.model_class._table_name}.{key}=%s"
            for key in kwargs
        ]

        sql = f"""
        UPDATE
            {self.model_class._table_name}
        SET {",".join(assignments)}
        {join_expression}
        {where_expression}
        """

        with conn.cursor() as cur:
            cur.execute(
                sql,
                [
                    *(
                        self.model_class._fields[key].to_sql(value) for key, value in kwargs.items()
                    ),
                    *literals,
                ],
            )
            conn.commit()

    def __len__(self):
        where_expression, join_expression, literals = self._resolve_where()
        sql = f"""
        SELECT
            COUNT(*)
        FROM
            {self.model_class._table_name}
        {join_expression}
        {where_expression}
        """

        with conn.cursor() as cur:
            cur.execute(sql, literals)
            return cur.fetchone()[0]


class Field:
    def __init__(self, type, **options):
        self._type = type
        self._name = None
        self._options = options

    def __repr__(self):
        return self._name

    def from_sql(self, sql):
        if sql is None:
            return None
        if self._type in [str, int]:
            return sql
        elif issubclass(self._type, Model):
            return self._type.get(sql)
        elif issubclass(self._type, Enum):
            return self._type(sql)
        raise TypeError(f"Don't know how to transform value of type {type(value)} from SQL")

    def to_sql(self, value=missing):
        if value is missing:  # when evaluated as part of a WHERE clause
            return f"{self._owner._table_name}.{self._name}"
        if value is None:
            return None  # NULL
        if self._type is str:
            return value
        if issubclass(self._type, Enum):
            return value.value
        if issubclass(self._type, Model):
            assert isinstance(value, self._type)
            value.save()
            return value.id
        if self._type is int:
            return value
        raise TypeError(f"Don't know how to transform value of type {type(value)} to SQL")


    def __get__(self, instance, owner=None):
        # self == Field
        # instance == customer
        # owner == Customer
        # get value from DB or cached (?)
        if instance is None:
            return self
        if self._options.get("virtual"):
            # example: some_addr.customers -> Customer.select(where=Customer.addr=some_addr)
            return self._type.select(
                where=getattr(self._type, self._options["forward_name"]) == instance,
            )
        return instance._values.get(self._name)

    def __set__(self, instance, value):
        # set value to DB or write-cache
        # TODO: casting / typechecking
        if value == instance._values.get(self._name):
            return
        assert isinstance(value, self._type)
        instance._values[self._name] = value
        if instance.id:
            if instance._initializing:
                pass
            else:
                instance._dirty = True
        else:
            instance._dirty = True

    def __set_name__(self, owner, name):
        # called on class definition time.
        # remember own name, etc.
        self._name = name
        self.desc = f"{name} DESC"
        self.asc = f"{name} ASC"
        self._owner = owner
        if name == "id":
            self._sql_type = "serial primary key"
        elif self._type is int:
            self._sql_type = "int"
        elif self._type is str:
            self._sql_type = f"varchar({self._options.get('max_length', 255)})"
        elif issubclass(self._type, Model):
            self._sql_type = "int"
        elif issubclass(self._type, Enum):
            self._sql_type = "int"
        else:
            raise RuntimeError(f"Don't know how to adapt type {self._type} to SQL")

    def __eq__(self, other):
        return Expression("=", [self, other])

    def __ne__(self, other):
        return Expression("!=", [self, other])

    def __lt__(self, other):
        return Expression("<", [self, other])

    def __gt__(self, other):
        return Expression(">", [self, other])

    def __le__(self, other):
        return Expression("<=", [self, other])

    def __ge__(self, other):
        return Expression(">=", [self, other])

    def __rand__(self, other):
        raise RuntimeError("You have to parenthesize your boolean expressions")

    def __ror__(self, other):
        raise RuntimeError("You have to parenthesize your boolean expressions")

    def __getattr__(self, attr):
        if not issubclass(self._type, Model):
            raise AttributeError(f"As {self._type.__name__} is not a Model, we can't access the attribute {attr}")
        return Expression(
            "join",
            [
                [
                    (
                        self._owner._table_name,
                        self._type._table_name,
                        self._name if not self._options.get("virtual") else "id",
                        "id" if not self._options.get("virtual") else self._options["forward_name"],
                    ),
                ],
                getattr(self._type, attr),
            ],
        )


class Expression:
    def __init__(self, operator, operands, join=None):
        self.operator = operator
        self.operands = operands

    def __getattr__(self, attr):
        if not issubclass(self.operands[-1]._type, Model) or self.operator != "join":
            raise AttributeError(f"As {self._type.__name__} is not a Model, we can't access the attribute {attr}")
        field = self.operands[-1]
        return Expression(
            "join",
            [
                [
                    *self.operands[0],
                    (
                        field._owner._table_name,
                        field._type._table_name,
                        field._name if not field._options.get("virtual") else "id",
                        "id" if not field._options.get("virtual") else field._options["forward_name"],
                    ),
                ],
                getattr(field._type, attr),
            ],
        )

    def __repr__(self):
        return f"<{self.operator}{self.operands}>"

    def __and__(self, other):
        return Expression("AND", [self, other])

    def __or__(self, other):
        return Expression("OR", [self, other])

    def __eq__(self, other):
        return Expression("=", [self, other])

    def __ne__(self, other):
        return Expression("!=", [self, other])

    def __lt__(self, other):
        return Expression("<", [self, other])

    def __gt__(self, other):
        return Expression(">", [self, other])

    def __le__(self, other):
        return Expression("<=", [self, other])

    def __ge__(self, other):
        return Expression(">=", [self, other])

    def to_sql(self):
        literals = []
        operands = []
        joins = []
        if self.operator == "join":
            if isinstance(self.operands[-1], Expression):
                sql_operand, inner_literals, inner_joins = self.operands[-1].to_sql()
                joins.extend(self.operands[0])
                joins.extend(inner_joins)
                literals.extend(inner_literals)
            else:
                joins.extend(self.operands[0])
                sql_operand = self.operands[-1].to_sql()
            operands.append(sql_operand)
        else:
            for operand in self.operands:
                if hasattr(operand, "to_sql"):
                    if isinstance(operand, Expression):
                        sql_operand, inner_literals, inner_joins = operand.to_sql()
                        operands.append(sql_operand)
                        literals.extend(inner_literals)
                        joins.extend(inner_joins)
                    else:  # Field
                        operands.append(operand.to_sql())
                else:  # literal(ish) value
                    if isinstance(operand, Enum):
                        operand = operand.value
                    elif isinstance(operand, Model):
                        operand = operand.id
                    literals.append(operand)
                    operands.append("%s")
        if self.operator == "join":
            return operands[0], literals, joins
        elif len(self.operands) == 1:
            return f"{self.operator} {operands[0]}", literals, joins
        elif len(self.operands) == 2:
            return f"{operands[0]} {self.operator} {operands[1]}", literals, joins
        else:
            raise RuntimeError("Fuckup in Expression: can't have more than 2 operands")
