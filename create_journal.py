import random
from odoo import fields

# ================================
# 1️⃣ Buat jurnal dummy (jika belum ada)
# ================================
journal = env['account.journal'].search([('code', '=', 'AC')], limit=1)
if not journal:
    journal = env['account.journal'].create({
        'name': 'Jurnal Accounting',
        'code': 'AC',
        'type': 'general',
    })
    env.cr.commit()  # commit supaya langsung tersimpan
print('Jurnal ID:', journal.id)

# ================================
# 2️⃣ Buat akun dummy (debit & kredit)
# ================================
account_debit = env['account.account'].search([('code', '=', '4000')], limit=1)
if not account_debit:
    account_debit = env['account.account'].create({
        'name': 'Debit Dummy',
        'code': '4000',
        'account_type': 'asset_current',
    })
    env.cr.commit()
print('Debit account ID:', account_debit.id)

account_credit = env['account.account'].search([('code', '=', '5000')], limit=1)
if not account_credit:
    account_credit = env['account.account'].create({
        'name': 'Credit Dummy',
        'code': '5000',
        'account_type': 'income',
    })
    env.cr.commit()
print('Credit account ID:', account_credit.id)

# ================================
# 3️⃣ Buat partner dummy (jika belum ada)
# ================================
partner = env['res.partner'].search([('name', '=', 'Partner Dummy')], limit=1)
if not partner:
    partner = env['res.partner'].create({'name': 'Partner Dummy'})
    env.cr.commit()
print('Partner ID:', partner.id)

# ================================
# 4️⃣ Generate journal entries
# ================================
N = 5  # jumlah journal entries
for i in range(1, N+1):
    try:
        amount = round(random.random() * 10000, 2)
        name = f'JE{i:08d}'

        move = env['account.move'].create({
            'name': name,
            'journal_id': journal.id,
            'move_type': 'entry',
            'date': fields.Date.today(),
            'line_ids': [
                (0, 0, {
                    'account_id': account_debit.id,
                    'partner_id': partner.id,
                    'name': 'Debit line',
                    'debit': amount,
                    'credit': 0.0,
                }),
                (0, 0, {
                    'account_id': account_credit.id,
                    'partner_id': partner.id,
                    'name': 'Credit line',
                    'debit': 0.0,
                    'credit': amount,
                }),
            ]
        })
        env.cr.commit()  # commit setiap entry supaya tidak hilang kalau error berikutnya
        print(f'Created journal entry {name} with amount {amount}')
    except Exception as e:
        print(f"Error creating journal entry {i}: {e}")

print('✅ Semua journal entries berhasil dibuat dan committed ke database.')

