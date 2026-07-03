from flask import request

def get_pagination_params(page_param='page', per_page_param='per_page', default_per_page=25):
    """
    Parses and sanitizes pagination parameters (page and per_page) from Flask request.args.
    Guarantees page >= 1, and per_page is one of [10, 25, 50, 100].
    
    :param page_param: URL query parameter name for page number (default: 'page')
    :param per_page_param: URL query parameter name for page size (default: 'per_page')
    :param default_per_page: Fallback page size value (default: 25)
    :returns: tuple (page, per_page)
    """
    try:
        page = int(request.args.get(page_param, 1))
        if page < 1:
            page = 1
    except (ValueError, TypeError):
        page = 1
        
    try:
        per_page = int(request.args.get(per_page_param, default_per_page))
        if per_page not in [10, 25, 50, 100]:
            per_page = default_per_page
    except (ValueError, TypeError):
        per_page = default_per_page
        
    return page, per_page
