from enum import Enum
import cuneiform as cf


class CompanyType(Enum):
    GmbH = 1
    AG = 2
    KG = 3
    other = 4

class Town(cf.Model):
    name = cf.Field(str)

class Address(cf.Model):
    street = cf.Field(str)
    house_number = cf.Field(int)  # jaja, eigentlich str..
    post_code = cf.Field(str, min_length=5, max_length=5)
    town = cf.Field(Town)

class Customer(cf.Model):
    name = cf.Field(str)
    type = cf.Field(CompanyType, default=None)
    addr = cf.Field(Address, default=None)

if __name__ == "__main__":
    s = Town(name="Stuttgart")
    ka = Town(name="Karlsruhe")

    solute_addr = Address(street="Zeppelinstraße", house_number=15, post_code="76137", town=ka)
    jo_addr = Address(street="Verschlusssache", house_number=23, post_code="70372", town=s)

    Customer(name="Jonathan, Inc.", type=CompanyType.KG, addr=jo_addr).save()
    solute = Customer(name="solute", type=CompanyType.GmbH, addr=solute_addr)
    solute.save()

    print("All customers:", list(Customer.select()))
    print("All customers in KA:", list(Customer.select(where=Customer.addr.town.name == "Karlsruhe")))
    print("All customers in KA, differently:", list(Customer.select(where=Customer.addr.town == ka)))
    print(
        "Complex, pointless query:",
        list(
            Customer.select(
                where=(Customer.addr.town.name == "Karlsruhe") | (Customer.type == CompanyType.AG),
            ),
        ),
    )
    print(
        "Reverse query:",
        list(
            Address.select(
                where=Address.customers.name == "solute",
            ),
        ),
    )

    print("All customers of solute addr:", solute_addr.customers)
