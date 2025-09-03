import time
from odoo import api, models, _
from odoo.exceptions import UserError


class ReportFinancial(models.AbstractModel):
    _name = 'report.accounting_pdf_reports.report_financial'
    _description = 'Financial Reports'

    def _compute_account_balance(self, accounts):
        """ compute the balance, debit and credit for the provided accounts
        """
        mapping = {
            'balance': "COALESCE(SUM(debit),0) - COALESCE(SUM(credit), 0) as balance",
            'debit': "COALESCE(SUM(debit), 0) as debit",
            'credit': "COALESCE(SUM(credit), 0) as credit",
        }

        res = {}
        for account in accounts:
            res[account.id] = dict.fromkeys(mapping, 0.0)
            
        if not accounts:
            return res
    
    def _compute_account_balance_orm(self, accounts):
        """ Alternative method using ORM instead of raw SQL - more reliable for Odoo 18
        """
        res = {}
        for account in accounts:
            res[account.id] = {
                'balance': 0.0,
                'debit': 0.0, 
                'credit': 0.0
            }
        
        if not accounts:
            return res
            
        try:
            # Build domain for account move lines
            domain = [('account_id', 'in', accounts.ids)]
            
            # Add context-based domain filters if available
            context = self.env.context
            if context.get('date_from'):
                domain.append(('date', '>=', context['date_from']))
            if context.get('date_to'):
                domain.append(('date', '<=', context['date_to']))
            if context.get('state'):
                if context['state'] == 'posted':
                    domain.append(('parent_state', '=', 'posted'))
            
            # Use read_group for better performance
            move_lines_data = self.env['account.move.line'].read_group(
                domain=domain,
                fields=['account_id', 'debit', 'credit', 'balance'],
                groupby=['account_id']
            )
            
            for line_data in move_lines_data:
                account_id = line_data['account_id'][0] if isinstance(line_data['account_id'], tuple) else line_data['account_id']
                res[account_id] = {
                    'balance': line_data.get('balance', 0.0),
                    'debit': line_data.get('debit', 0.0),
                    'credit': line_data.get('credit', 0.0)
                }
                
        except Exception as e:
            import logging
            _logger = logging.getLogger(__name__)
            _logger.error(f"Error in _compute_account_balance_orm: {e}")
            # Return empty results but don't break the report
            
        return res
            
        try:
            # Get the proper domain and convert to SQL using _query_get()
            AccountMoveLine = self.env['account.move.line']
            
            # Build the domain - this should come from context or be empty
            domain = []
            
            # Try to get query components from _query_get()
            # In Odoo 18, _query_get() might work differently
            try:
                query_result = AccountMoveLine._query_get(domain)
                
                # Handle different return formats
                if isinstance(query_result, tuple) and len(query_result) >= 3:
                    tables, where_clause, where_params = query_result[0], query_result[1], query_result[2]
                elif isinstance(query_result, dict):
                    # Some versions might return a dict
                    tables = query_result.get('tables', 'account_move_line')
                    where_clause = query_result.get('where_clause', '')
                    where_params = query_result.get('where_params', [])
                else:
                    # Fallback to default values
                    tables = 'account_move_line'
                    where_clause = ''
                    where_params = []
                    
            except (AttributeError, TypeError) as e:
                # If _query_get() doesn't work as expected, use manual approach
                import logging
                _logger = logging.getLogger(__name__)
                _logger.warning(f"_query_get() failed, using fallback: {e}")
                tables = 'account_move_line'
                where_clause = ''
                where_params = []
            
            # Normalize tables - handle list/tuple format
            if isinstance(tables, (list, tuple)):
                tables = ', '.join(str(table).strip('"').strip("'") for table in tables if table)
            elif isinstance(tables, str):
                tables = tables.replace('"', '').replace("'", '')
            
            # Ensure we have valid table name
            if not tables or not tables.strip():
                tables = 'account_move_line'
                
            # Clean and prepare where clause
            if where_clause:
                where_clause = where_clause.strip()
                # Make sure where_clause doesn't contain domain tuples
                if where_clause.startswith('(') and ')' in where_clause and ',' in where_clause:
                    # This looks like a domain, not a proper SQL WHERE clause
                    where_clause = ''
                    where_params = []
            
            # Build the complete query
            where_parts = []
            if where_clause:
                where_parts.append(f"({where_clause})")
            where_parts.append("account_id IN %s")
            
            full_where = " AND ".join(where_parts) if where_parts else "account_id IN %s"
            
            query = f"""
                SELECT account_id as id, {', '.join(mapping.values())}
                FROM {tables}
                WHERE {full_where}
                GROUP BY account_id
            """
            
            # Prepare parameters
            params = list(where_params) if where_params else []
            params.append(tuple(accounts.ids))
            
            # Execute query
            self.env.cr.execute(query, params)
            for row in self.env.cr.dictfetchall():
                res[row['id']] = row
                
        except Exception as e:
            # Log the error for debugging
            import logging
            _logger = logging.getLogger(__name__)
            _logger.error(f"Error in _compute_account_balance: {e}")
            _logger.error(f"Accounts: {accounts.ids}")
            # Return empty results on error but don't break the report
            pass
            
        return res

    def _compute_report_balance(self, reports):
        '''returns a dictionary with key=the ID of a record and value=the credit, debit and balance amount
           computed for this record. If the record is of type :
               'accounts' : it's the sum of the linked accounts
               'account_type' : it's the sum of leaf accounts with such an account_type
               'account_report' : it's the amount of the related report
               'sum' : it's the sum of the children of this record (aka a 'view' record)'''
        res = {}
        fields = ['credit', 'debit', 'balance']
        for report in reports:
            if report.id in res:
                continue
            res[report.id] = dict((fn, 0.0) for fn in fields)
            if report.type == 'accounts':
                # it's the sum of the linked accounts
                # Try ORM method first, fallback to SQL method if needed
                try:
                    res[report.id]['account'] = self._compute_account_balance_orm(report.account_ids)
                except:
                    res[report.id]['account'] = self._compute_account_balance(report.account_ids)
                    
                for value in res[report.id]['account'].values():
                    for field in fields:
                        res[report.id][field] += value.get(field, 0.0)
            elif report.type == 'account_type':
                # it's the sum the leaf accounts with such an account type
                # Handle potential changes in account_type field structure
                account_types = []
                if hasattr(report, 'account_type_ids') and report.account_type_ids:
                    # If account_type_ids exists and has mapped method
                    if hasattr(report.account_type_ids, 'mapped'):
                        account_types = report.account_type_ids.mapped('type')
                    else:
                        # Fallback for different field structures
                        account_types = [t.type for t in report.account_type_ids if hasattr(t, 'type')]
                elif hasattr(report, 'account_type') and report.account_type:
                    # Direct account_type field
                    account_types = [report.account_type]
                
                if account_types:
                    accounts = self.env['account.account'].search([
                        ('account_type', 'in', account_types)
                    ])
                    # Try ORM method first, fallback to SQL method if needed
                    try:
                        res[report.id]['account'] = self._compute_account_balance_orm(accounts)
                    except:
                        res[report.id]['account'] = self._compute_account_balance(accounts)
                        
                    for value in res[report.id]['account'].values():
                        for field in fields:
                            res[report.id][field] += value.get(field, 0.0)
            elif report.type == 'account_report' and report.account_report_id:
                # it's the amount of the linked report
                res2 = self._compute_report_balance(report.account_report_id)
                for key, value in res2.items():
                    for field in fields:
                        res[report.id][field] += value[field]
            elif report.type == 'sum':
                # it's the sum of the children of this account.report
                res2 = self._compute_report_balance(report.children_ids)
                for key, value in res2.items():
                    for field in fields:
                        res[report.id][field] += value[field]
        return res

    def get_account_lines(self, data):
        lines = []
        account_report = self.env['account.financial.report'].search(
            [('id', '=', data['account_report_id'][0])])
        child_reports = account_report._get_children_by_order()
        res = self.with_context(data.get('used_context'))._compute_report_balance(child_reports)
        
        if data['enable_filter']:
            comparison_res = self.with_context(
                data.get('comparison_context'))._compute_report_balance(
                child_reports)
            for report_id, value in comparison_res.items():
                res[report_id]['comp_bal'] = value['balance']
                report_acc = res[report_id].get('account')
                if report_acc:
                    for account_id, val in comparison_res[report_id].get('account', {}).items():
                        report_acc[account_id]['comp_bal'] = val['balance']
        
        for report in child_reports:
            vals = {
                'name': report.name,
                'balance': res[report.id]['balance'] * float(report.sign),
                'type': 'report',
                'level': bool(report.style_overwrite) and report.style_overwrite or report.level,
                'account_type': report.type or False, #used to underline the financial report balances
            }
            if data['debit_credit']:
                vals['debit'] = res[report.id]['debit']
                vals['credit'] = res[report.id]['credit']

            if data['enable_filter']:
                vals['balance_cmp'] = res[report.id]['comp_bal'] * float(report.sign)

            lines.append(vals)
            if report.display_detail == 'no_detail':
                #the rest of the loop is used to display the details of the financial report, so it's not needed here.
                continue
                
            if res[report.id].get('account'):
                sub_lines = []
                for account_id, value in res[report.id]['account'].items():
                    #if there are accounts to display, we add them to the lines with a level equals to their level in
                    #the COA + 1 (to avoid having them with a too low level that would conflicts with the level of data
                    #financial reports for Assets, liabilities...)
                    flag = False
                    account = self.env['account.account'].browse(account_id)
                    vals = {
                        'name': account.code + ' ' + account.name,
                        'balance': value['balance'] * float(report.sign) or 0.0,
                        'type': 'account',
                        'level': report.display_detail == 'detail_with_hierarchy' and 4,
                        'account_type': account.account_type,
                    }
                    if data['debit_credit']:
                        vals['debit'] = value['debit']
                        vals['credit'] = value['credit']
                        # Handle currency_id compatibility
                        currency = self.env.company.currency_id
                        if hasattr(currency, 'is_zero'):
                            if not currency.is_zero(vals['debit']) or not currency.is_zero(vals['credit']):
                                flag = True
                        else:
                            # Fallback if is_zero method doesn't exist
                            if vals['debit'] != 0.0 or vals['credit'] != 0.0:
                                flag = True
                    
                    # Handle balance check
                    currency = self.env.company.currency_id
                    if hasattr(currency, 'is_zero'):
                        if not currency.is_zero(vals['balance']):
                            flag = True
                    else:
                        if vals['balance'] != 0.0:
                            flag = True
                    
                    if data['enable_filter']:
                        vals['balance_cmp'] = value.get('comp_bal', 0.0) * float(report.sign)
                        if hasattr(currency, 'is_zero'):
                            if not currency.is_zero(vals['balance_cmp']):
                                flag = True
                        else:
                            if vals['balance_cmp'] != 0.0:
                                flag = True
                    
                    if flag:
                        sub_lines.append(vals)
                lines += sorted(sub_lines, key=lambda sub_line: sub_line['name'])
        return lines

    @api.model
    def _get_report_values(self, docids, data=None):
        if not data.get('form') or not self.env.context.get('active_model') or not self.env.context.get('active_id'):
            raise UserError(_("Form content is missing, this report cannot be printed."))

        model = self.env.context.get('active_model')
        docs = self.env[model].browse(self.env.context.get('active_id'))
        report_lines = self.get_account_lines(data.get('form'))
        return {
            'doc_ids': self.ids,
            'doc_model': model,
            'data': data['form'],
            'docs': docs,
            'time': time,
            'get_account_lines': report_lines,
        }
