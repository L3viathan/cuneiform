from enum import Enum
import ozee

class CompanyType(Enum):
    GmbH = 1
    AG = 2
    KG = 3
    other = 4

# >>> repr(CompanyType.GmbH)
# CompanyType.GmbH
# >>> CompanyType(2)
# CompanyType.AG

class Customer(ozee.Model):
    name = ozee.Field(str)
    type = ozee.Field(CompanyType)

if __name__ == "__main__":
    # c1 = Customer(name="Krauss-Maffei", type=CompanyType.GmbH)
    # c2 = Customer(name="Howaldwerke", type=CompanyType.AG)
    # c2.type=CompanyType.KG
    # c1.save()
    # c2.save()
    # customer_id = c1.id

    # c = Customer.get(customer_id)
    # print("Name before:", c.name)
    # c.name = "Rheinmetall"
    # c.save()
    # c = Customer.get(customer_id)
    # print("Name after:", c.name)
    for customer in Customer.select(
        limit=20,
        order_by=(Customer.name.desc, Customer.id.asc),
    ):
        print(customer)
    print("Nur solute:")
    for customer in Customer.select(
        where=Customer.name == "solute",
        order_by=Customer.id.desc,  # order by lower(name) asc
    ):
        print(customer)

    cust = Customer.select(Customer.id < 100)
    cust.update(Customer.type=CompanyType.KG)
    cust.filter(name="BOSCH").delete()
    cust.filter(name="Siemens").update(...)
    cust.delete()



    # TODO:
    # - search/filter, recordset and its methods (update, delete, ...)
    # - relation stuff (foreign keys, ...)
    # - database state management (migrations etc.)
