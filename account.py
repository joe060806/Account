def add_transaction(transactions, next_id, payer, amount, splits, desc):
    new_t = {
        "id": next_id,
        "payer": payer,
        "amount": amount,
        "splits": splits,
        "desc": desc
    }
    transactions.append(new_t)
    return new_t


def calculate_balance(transactions):
    balance = {}

    for t in transactions:
        payer = t["payer"]
        amount = t["amount"]

        balance[payer] = balance.get(payer, 0) + amount

        for person, share in t["splits"].items():
            balance[person] = balance.get(person, 0) - share

    return balance


def settle_debts(balance):
    creditors = []
    debtors = []

    for person, amt in balance.items():
        if amt > 0:
            creditors.append([person, amt])
        elif amt < 0:
            debtors.append([person, -amt])

    i, j = 0, 0
    result = []

    while i < len(debtors) and j < len(creditors):
        debtor, debt = debtors[i]
        creditor, credit = creditors[j]

        pay = min(debt, credit)

        result.append({
            "from": debtor,
            "to": creditor,
            "amount": round(pay, 2)
        })

        debtors[i][1] -= pay
        creditors[j][1] -= pay

        if debtors[i][1] == 0:
            i += 1
        if creditors[j][1] == 0:
            j += 1

    return result