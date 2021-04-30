from enum import Enum
import psycopg2

conn = psycopg2.connect("dbname=ozee user=ozee password=ozee")

missing = object()

class Model:
    def __init_subclass__(subclass):
        fields = {}
        for field, value in vars(subclass).items():
            if field == "id":
                raise RuntimeError("Can't explicitly define an 'id' field")
            if isinstance(value, Field):
                fields[field] = value
        fields["id"] = Field(int, required=True)
        fields["id"].__set_name__(subclass, "id")
        setattr(subclass, "id", fields["id"])
        subclass._fields = fields
        subclass._table_name = subclass.__name__.lower()  # FIXME CamelCase etc. ABCFoo

    def __init__(self, **kwargs):
        self._initializing = True
        self._values = {}
        self._dirty = False
        for k, v in kwargs.items():
            assert k in self._fields, f"{k} is not in fields of {self}, only {self._fields}"
            setattr(self, k, v)
        for k, v in self._fields.items():
            if v.required and k != "id":
                assert k in kwargs, (k, kwargs, v.required)
        self._initializing = False

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
    def create(cls):
        field_list = {
            f"{name} {field.sql_type}"
            for name, field in cls._fields.items()
        }
        foreign_keys = []
        for name, field in cls._fields.items():
            if issubclass(field.type, Model):
                field.type.create()
                foreign_keys.append((name, field.type))

        sql = f"""
        CREATE TABLE IF NOT EXISTS
            {cls._table_name}
        ({', '.join(field_list)})
        """
        with conn.cursor() as cur:
            cur.execute(sql)
            for fk_name, fk_field in foreign_keys:
                sql = f"""
                ALTER TABLE {cls._table_name} DROP CONSTRAINT IF EXISTS fk_{fk_name};
                ALTER TABLE {cls._table_name} ADD CONSTRAINT fk_{fk_name} FOREIGN KEY ({fk_name}) REFERENCES {fk_field._table_name}(id);
                """
                cur.execute(sql)
            conn.commit()

    @classmethod
    def get(cls, id):
        # return instance from database or cache
        columns = cls._fields
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
                    ),
                    self.id,
                ])
                conn.commit()
        else:
            columns, values = [], []
            for k, v in self._fields.items():
                if k == "id":
                    continue
                columns.append(k)
                default = v.options.get("default", missing)
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
                "JOIN {foreign} ON {foreign}.id = {source}.{column}".format(
                    foreign=foreign,
                    source=source,
                    column=column,
                ) for source, foreign, column in joins
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
    def __init__(self, type, required=False, **options):
        self.type = type
        self.name = None
        self.required = required
        self.options = options

    def __repr__(self):
        return self.name

    def from_sql(self, sql):
        if sql is None:
            return None
        if self.type in [str, int]:
            return sql
        elif issubclass(self.type, Model):
            return self.type.get(sql)
        elif issubclass(self.type, Enum):
            return self.type(sql)
        raise TypeError(f"Don't know how to transform value of type {type(value)} from SQL")

    def to_sql(self, value=missing):
        if value is missing:  # when evaluated as part of a WHERE clause
            return f"{self.owner._table_name}.{self.name}"
        if value is None:
            return None  # NULL
        if self.type is str:
            return value
        if issubclass(self.type, Enum):
            return value.value
        if issubclass(self.type, Model):
            assert isinstance(value, self.type)
            value.save()
            return value.id
        if self.type is int:
            return value
        raise TypeError(f"Don't know how to transform value of type {type(value)} to SQL")


    def __get__(self, instance, owner=None):
        # self == Field
        # instance == customer
        # owner == Customer
        # get value from DB or cached (?)
        if instance is None:
            return self
        return instance._values.get(self.name)

    def __set__(self, instance, value):
        # set value to DB or write-cache
        # TODO: casting / typechecking
        if value == instance._values.get(self.name):
            return
        assert isinstance(value, self.type)
        instance._values[self.name] = value
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
        self.name = name
        self.desc = f"{name} DESC"
        self.asc = f"{name} ASC"
        self.owner = owner
        if name == "id":
            self.sql_type = "serial primary key"
        elif self.type is int:
            self.sql_type = "int"
        elif self.type is str:
            self.sql_type = f"varchar({self.options.get('max_length', 255)})"
        elif issubclass(self.type, Model):
            self.sql_type = "int"
        elif issubclass(self.type, Enum):
            self.sql_type = "int"
        else:
            raise RuntimeError(f"Don't know how to adapt type {self.type} to SQL")

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
        if not issubclass(self.type, Model):
            raise AttributeError(f"As {self.type.__name__} is not a Model, we can't access the attribute {attr}")
        return Expression(
            "join",
            [
                [
                    (
                        self.owner._table_name,
                        self.type._table_name,
                        self.name,
                    ),
                ],
                getattr(self.type, attr),
            ],
        )


class Expression:
    def __init__(self, operator, operands, join=None):
        self.operator = operator
        self.operands = operands

    def __getattr__(self, attr):
        if not issubclass(self.operands[-1].type, Model) or self.operator != "join":
            raise AttributeError(f"As {self.type.__name__} is not a Model, we can't access the attribute {attr}")
        field = self.operands[-1]
        return Expression(
            "join",
            [
                [
                    *self.operands[0],
                    (
                        field.owner._table_name,
                        field.type._table_name,
                        field.name,
                    ),
                ],
                getattr(field.type, attr),
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
