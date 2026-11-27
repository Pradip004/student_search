from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Lower
from django.http import Http404
from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.http import require_POST
from .file_uploads import UploadFileError, parse_people_upload
from .forms import PeopleImportForm, PeopleUploadForm, PersonForm
from .models import Person, SearchHistory
from .llm import ask_ai, build_queryset
from . import exports


def _search_context(request, **extra):
    context = {
        "results": [],
        "q": "",
        "history": None,
        "mode": "",
        "search_history": SearchHistory.objects.filter(
            session_key=get_session_key(request)
        ).order_by("-created_at"),
        "upload_form": PeopleUploadForm(),
        "file_search": False,
        "file_name": "",
        "result_count": 0,
    }
    context.update(extra)
    return render(request, "search.html", context)


def get_session_key(request):
    # No login required: keep a simple anonymous session key for browser history.
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


def search(request):
    q = request.GET.get("q", "").strip()
    session_key = get_session_key(request)
    results, history, mode = [], None, ""
    if q:
        filters = ask_ai(q)
        if filters:
            mode = "AI search"
        else:
            filters = {"_keyword": q}
            mode = "Keyword search"
        results = build_queryset(filters)
        history = SearchHistory.objects.create(
            session_key=session_key,
            query_text=q,
            filters=filters,
            result_count=results.count(),
        )
    return _search_context(
        request,
        results=results,
        q=q,
        history=history,
        mode=mode,
        result_count=history.result_count if history else 0,
    )


def _search_people(records):
    emails = {
        record["email"].strip()
        for record in records
        if record.get("email", "").strip()
    }
    names = {
        record["name"].strip()
        for record in records
        if record.get("name", "").strip()
    }
    if not emails and not names:
        raise UploadFileError(
            "The file must include at least one name or email address."
        )

    matches = {}
    values = [("email", value) for value in emails]
    values.extend(("name", value) for value in names)
    for start in range(0, len(values), 100):
        condition = Q()
        for field, value in values[start:start + 100]:
            condition |= Q(**{f"{field}__iexact": value})
        matches.update(
            (person.pk, person)
            for person in Person.objects.filter(condition)
        )
    return sorted(matches.values(), key=lambda person: person.name.casefold())


@require_POST
def search_upload(request):
    form = PeopleUploadForm(request.POST, request.FILES)
    results = []
    filename = ""
    if form.is_valid():
        uploaded_file = form.cleaned_data["upload_file"]
        filename = uploaded_file.name
        try:
            results = _search_people(parse_people_upload(uploaded_file))
        except UploadFileError as error:
            messages.error(request, str(error))
        else:
            messages.success(
                request,
                f"File search matched {len(results)} existing record(s).",
            )
    return _search_context(
        request,
        upload_form=form,
        results=results,
        file_search=True,
        file_name=filename,
        result_count=len(results),
    )


def history_list(request):
    items = SearchHistory.objects.filter(
        session_key=get_session_key(request)
    ).order_by("-created_at")
    return render(request, "history.html", {"items": items})


@require_POST
def delete_search_history(request, history_id):
    item = get_object_or_404(
        SearchHistory,
        id=history_id,
        session_key=get_session_key(request),
    )
    item.delete()
    messages.success(request, "Search history entry deleted.")
    return redirect("history")


def add_person(request):
    form = PersonForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Student/candidate details added.")
        return redirect("add_person")
    return render(
        request,
        "add_person.html",
        {
            "form": form,
            "upload_form": PeopleUploadForm(),
            "import_form": PeopleImportForm(),
        },
    )


@require_POST
def import_people(request):
    import_form = PeopleImportForm(request.POST, request.FILES)
    if not import_form.is_valid():
        messages.error(
            request,
            "Choose a file and a default category before importing records.",
        )
        return redirect("add_person")

    try:
        records = parse_people_upload(import_form.cleaned_data["upload_file"])
    except UploadFileError as error:
        messages.error(request, str(error))
        return redirect("add_person")

    default_person_type = import_form.cleaned_data["person_type"]
    valid_forms = []
    invalid_rows = []
    for row_number, record in enumerate(records, start=2):
        if not record.get("person_type", "").strip():
            record["person_type"] = default_person_type
        form = PersonForm(record)
        if form.is_valid():
            valid_forms.append((row_number, form))
        else:
            invalid_rows.append((row_number, form.errors))

    if invalid_rows:
        messages.error(
            request,
            f"Import cancelled: {len(invalid_rows)} row(s) need correction. "
            "No records were saved.",
        )
        for row_number, errors in invalid_rows[:5]:
            messages.error(request, f"Row {row_number}: {errors.as_text()}")
        return redirect("add_person")

    email_keys = {
        form.cleaned_data["email"].strip().casefold()
        for _, form in valid_forms
        if form.cleaned_data["email"].strip()
    }
    existing_emails = set(
        Person.objects.annotate(normalized_email=Lower("email"))
        .filter(normalized_email__in=email_keys)
        .values_list("normalized_email", flat=True)
    ) if email_keys else set()

    imported = 0
    skipped = 0
    seen_emails = set(existing_emails)
    with transaction.atomic():
        for _, form in valid_forms:
            email = form.cleaned_data["email"].strip().casefold()
            if email and email in seen_emails:
                skipped += 1
                continue
            form.save()
            imported += 1
            if email:
                seen_emails.add(email)

    if imported:
        messages.success(request, f"Imported {imported} person record(s).")
    if skipped:
        messages.info(
            request,
            f"Skipped {skipped} record(s) with duplicate email addresses.",
        )
    return redirect("add_person")


def edit_person(request, person_id):
    person = get_object_or_404(Person, id=person_id)
    form = PersonForm(request.POST or None, instance=person)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Person details updated.")
        return redirect("remove_person")
    return render(
        request,
        "person_form.html",
        {"form": form, "person": person},
    )


def remove_person(request):
    people = Person.objects.order_by("-created_at")
    return render(request, "remove_person.html", {"people": people})


@require_POST
def delete_person(request, person_id):
    person = get_object_or_404(Person, id=person_id)
    person.delete()
    messages.success(request, "Student/candidate details removed.")
    return redirect("remove_person")


def export(request, history_id, fmt):
    h = get_object_or_404(SearchHistory, id=history_id,
                          session_key=get_session_key(request))
    qs = build_queryset(h.filters)
    if fmt == "xlsx":
        return exports.to_excel(qs)
    if fmt == "docx":
        return exports.to_word(qs)
    if fmt == "pdf":
        return exports.to_pdf(qs)
    raise Http404()