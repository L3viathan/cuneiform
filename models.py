from enum import Enum
import cuneiform as cf

class CompanyType(Enum):
    GmbH = 1
    AG = 2
    KG = 3
    other = 4

class Address(cf.Model):
    street = cf.Field(str)
    house_number = cf.Field(int)  # jaja, eigentlich str..
    post_code = cf.Field(str, min_length=5, max_length=5)
    town = cf.Field(str)

# >>> repr(CompanyType.GmbH)
# CompanyType.GmbH
# >>> CompanyType(2)
# CompanyType.AG

class Customer(cf.Model):
    name = cf.Field(str)
    type = cf.Field(CompanyType, default=None)
    addr = cf.Field(Address, default=None)

if __name__ == "__main__":
    # addr = Address(street="Zeppelinstraße", house_number=15, post_code="76135", town="Karlsruhe")
    # cust = Customer(name="solute", type=CompanyType.GmbH, address=addr)
    # cust.save()

    expr = Customer.addr.house_number == 15
    print("hn ??:", list(Customer.select()))
    print("hn 15:", list(Customer.select(where=Customer.addr.house_number == 15)))

    # TODO:
    # - search/filter, recordset and its methods (update, delete, ...)
    # - relation stuff (foreign keys, ...)
    # - database state management (migrations etc.)
