from enum import Enum
import ozee

class CompanyType(Enum):
    GmbH = 1
    AG = 2
    KG = 3
    other = 4

class Address(ozee.Model):
    street = ozee.Field(str)
    house_number = ozee.Field(int)  # jaja, eigentlich str..
    post_code = ozee.Field(str, min_length=5, max_length=5)
    town = ozee.Field(str)

# >>> repr(CompanyType.GmbH)
# CompanyType.GmbH
# >>> CompanyType(2)
# CompanyType.AG

class Customer(ozee.Model):
    name = ozee.Field(str)
    type = ozee.Field(CompanyType, default=None)
    addr = ozee.Field(Address, default=None)

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
