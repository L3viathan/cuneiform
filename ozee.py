from enum import Enum
import psycopg2

conn = psycopg2.connect("dbname=ozee user=ozee password=ozee")

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
            assert k in self._fields
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
        if self.id:
            assignments = [
                f"{key}=%s"
                for key in self._fields
                if key != "id"
            ]
            sql = f"""
            UPDATE {self._table_name}
            SET {",".join(assignments)}
            WHERE id = %s;
            COMMIT;
            """
            with conn.cursor() as cur:
                cur.execute(sql, [
                    *(
                        v.to_sql(self._values[k])
                        for (k, v) in self._fields.items()
                        if k != "id"
                    ),
                    self.id,
                ])
        else:
            columns, values = [], []
            for k, v in self._fields.items():
                if k == "id":
                    continue
                columns.append(k)
                values.append(v.to_sql(self._values[k]))
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
                cur.execute("COMMIT")
        self._dirty = False

    @classmethod
    def select(cls, where=None, limit=None, order_by=None):
        if where:
            where_sql, literals = where.to_sql()
            where_expression = f"WHERE {where_sql}"
        else:
            where_expression = ""
            literals = []

        limit_expression = f"LIMIT {int(limit)}" if limit else ""
        if isinstance(order_by, tuple):
            order_by = f"{', '.join(order_by)}"
        order_by_expression = f"ORDER BY {order_by}" if order_by else ""

        sql = f"""
        SELECT
            id
        FROM
            {cls._table_name}
        {where_expression}
        {order_by_expression}
        {limit_expression}
        """
        with conn.cursor() as cur:
            cur.execute(sql, literals)
            for row in cur.fetchall():
                yield cls.get(row[0])


class RecordSet:
    def __init__(self, model, ids):
        ...

class Field:
    def __init__(self, type, required=False, **options):
        self.type = type
        self.name = None
        self.required = required
        self.options = options

    def __repr__(self):
        return self.name

    def from_sql(self, sql):
        if self.type in [str, int]:
            return sql
        elif issubclass(self.type, Enum):
            return self.type(sql)
        raise TypeError(f"Don't know how to transform value of type {type(value)} from SQL")

    def to_sql(self, value=None):
        if value is None:  # when evaluated as part of a WHERE clause
            return self.name
        if self.type is str:
            return value
        if issubclass(self.type, Enum):
            return value.value
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

    def __eq__(self, other):
        return Expression("=", [self, other])

    def __ne__(self, other):
        return Expression("!=", [self, other])

    def __lt__(self, other):
        return Expression("<", [self, other])

    def __gt__(self, other):
        return Expression(">", [self, other])

    def __rand__(self, other):
        raise RuntimeError("You have to parenthesize your boolean expressions")

class Expression:
    def __init__(self, operator, operands):
        self.operator = operator
        self.operands = operands

    def __repr__(self):
        a, b = self.operands
        return f"<{a!r} {self.operator} {b!r}>"

    def __and__(self, other):
        return Expression("AND", [self, other])

    def __or__(self, other):
        return Expression("OR", [self, other])

    def to_sql(self):
        literals = []
        operands = []
        for operand in self.operands:
            if hasattr(operand, "to_sql"):
                if isinstance(operand, Expression):
                    sql_operand, inner_literals = operand.to_sql()
                    operands.append(sql_operand)
                    literals.extend(inner_literals)
                else:  # Field
                    operands.append(operand.to_sql())
            else:  # literal value
                literals.append(operand)
                operands.append("%s")
        if len(self.operands) == 1:
            return f"{self.operator} {operands[0]}", literals
        elif len(self.operands) == 2:
            return f"{operands[0]} {self.operator} {operands[1]}", literals
        else:
            raise RuntimeError("Fuckup in Expression: can't have more than 2 operands")
