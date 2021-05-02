# cuneiform

*cuneiform* is the result of a Learning Day @ solute; we tried to build an ORM in a day.


## Setup

cuneiform is relatively self-contained, it just needs psycopg2 installed and a postgres database.

## Tutorial

Start by importing cuneiform and configuring the database connection:

```python
import cuneiform as cf

cf.configure(db="cuneiform", user="cuneiform", password="cuneiform")
```

### Models

You can then start defining models. Lets start with a simple CRM for no reason whatsoever:

```python
from enum import Enum

class CompanyType(Enum):
    Ltd = 1
    Inc = 2
    SE = 3
    AB = 4
    GmbH = 5

class Company(cf.Model):
    name = cf.Field(str)
    type = cf.Field(CompanyType)
```

As you can see, you define a model by subclassing `cf.Model` and declare its
fields using `cf.Field(some_type)`. For simple columns with one out of a small
number of values, you can use an Enum, which gets translated into an int column
internally (but cuneiform will make sure you only assign e.g. `CompanyType`
instances to it).

Cuneiform will now automatically create the necessary table and we can start
inserting some rows:

```python
>>> solute = Company(name="solute", type=CompanyType.GmbH)
>>> solute
<Company[D] name='solute' type=CompanyType.GmbH>
```

As you can see, the resulting object was marked with the "dirty" flag (`[D]`),
meaning it was not yet written to the database. To do that, you call `.save()`:

```python
>>> solute.save()
```

### Recordsets

We can now also retrieve this instance by searching for it in various ways:

```python
>>> rs = Company.select(where=Company.name == "solute")
>>> rs = Company.select(where=Company.type == CompanyType.GmbH)
>>> rs = Company.select(where=(Company.type == CompanyType.GmbH) & (Company.name == "solute"))
```

All these queries return the same thing: a lazy recordset describing the
eventual query to be made. To actually return instances, we can iterate over
them (or call `list()`). In case we _know_ there can only be one row, we can
also call `.get()`:

```python
>>> list(rs)
[<Company name='solute' type=CompanyType.GmbH>]
>>> rs.get()
<Company name='solute' type=CompanyType.GmbH>
```

Recordsets also support limits and orderings. All of these can be added in the
initial `.select()` call, or later with methods that return another RecordSet.
The following lines are all equivalent:

```python
>>> rs = Company.select(where=Company.name == "solute", order_by=Company.name.asc, limit=23)
>>> rs = Company.select(where=Company.name == "solute").order_by(Company.name.asc).limit(23)
>>> rs = Company.select().order_by(Company.name.asc).limit(23).filter(Company.name == "solute")
```

Finally, in addition to retrieving objects from a record set, you can also
perform bulk operations like deletions (with `.delete()`) and updates (e.g.
`.update(name="new name")`)

### Relations

We now have *O*bjects that are *M*apped into a database, but no relationality
yet. Let's define another model:

```python
class Address(cf.Model):
    street = cf.Field(str)
    house = cf.Field(int)
    post_code = cf.Field(str)
    town = cf.Field(str)
```

In order to link these together, lets add a new column to our `Company` model:

```python
class Company(cf.Model):
    name = cf.Field(str)
    type = cf.Field(CompanyType)
    addr = cf.Field(Address)
```

Make sure to define `Address` above `Company` so you don't get a NameError.
Cuneiform will automatically take care of adding the new column to the
company table and setting up a foreign key relation. Lets augment our existing customer:

```python
>>> solute = Company.select(where=Company.name=="solute")
>>> address = Address(street="Zeppelinstraße", house=15, post_code="76185", town="Karlsruhe")
>>> solute.addr = address
>>> solute.save()
```

The `.save()` method recursively makes sure that all dependent objects are
saved as well, so we don't have to explicitly save the address.

Lets see what querying possibilities we have gained:

```python
>>> Company.select(where=Company.addr.town=="Karlsruhe").get()
<Company name='solute' type=CompanyType.GmbH>
>>> address.companies.get()
<Company name='solute' type=CompanyType.GmbH>
```

Wait, what, `companies`? Cuneiform automatically adds reverse relations to the
referenced models as well, defaulting to the plural form of the source model.
`address.companies` is a RecordSet containing all companies that have this
address set.


### Quirks and small features

- Because it is impossible to override the `and` and `or` operators in Python, we
  had to resort to using `&` and `|`. Since they have a much stronger precedence
  than the textual versions, you always need to paranthesize your inner
  expressions when combining them like this. Thankfully, we can at least make
  sure you do so, because we define `__ror__` and `__rand__` on the Field class.
- Recordsets also support length querying via `len()`.
- In its current state, cuneiform is very brutal when it comes to model
  changes. It will delete and recreate your tables or columns without
  hesitation when it thinks it needs to. Think of it as a warning not to
  actually use this anywhere serious.
