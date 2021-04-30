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
    c1 = Customer(name="Firma A", type=CompanyType.GmbH)
    c2 = Customer(name="Firma B", type=CompanyType.AG)
    c2.type=CompanyType.KG
    c1.save()
    c2.save()
    customer_id = c1.id

    c = Customer.get(customer_id)
    print("Name before:", c.name)
    c.name = "Rheinmetall"
    c.save()
    c = Customer.get(customer_id)
    print("Name after:", c.name)
    for customer in Customer.select(
        limit=20,
        order_by=(Customer.name.desc, Customer.id.asc),
    ):
        print(customer)

    cust = Customer.select(where=Customer.id < 100)
    print("rs:", cust, len(cust))
    cust.filter(Customer.name=="Firma B").delete()
    print("after delete n rows:", len(cust))
    cust.filter(Customer.name=="Firma A").update(name="BOSCH")
    cust.update(type=CompanyType.KG)
    for customer in Customer.select(
        limit=20,
        order_by=(Customer.name.desc, Customer.id.asc),
    ):
        print(customer)
    cust.delete()
    print("final n rows:", len(cust))



    # TODO:
    # - search/filter, recordset and its methods (update, delete, ...)
    # - relation stuff (foreign keys, ...)
    # - database state management (migrations etc.)
