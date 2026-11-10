from django.core.paginator import Paginator


def paginate(request, items, per=50, param="page"):
    """One page of `items`, with what a pager needs to link to its neighbours
    while keeping every other filter in the address."""
    page = Paginator(items, per).get_page(request.GET.get(param))
    others = request.GET.copy()
    others.pop(param, None)
    page.param = param
    page.base = others.urlencode()
    return page
