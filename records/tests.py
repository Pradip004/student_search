import io
from django.test import Client, TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from unittest.mock import patch

from docx import Document
from openpyxl import Workbook
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from .file_uploads import (
    MAX_UPLOAD_SIZE,
    UploadFileError,
    parse_people_upload,
)
from .models import Person, SearchHistory


class SearchHistorySidebarTests(TestCase):
    def test_history_page_renders_shared_navigation(self):
        response = self.client.get("/history/")

        self.assertContains(response, "Search history")
        self.assertContains(response, "no saved searches yet")

    def test_homepage_shows_search_history_for_current_session(self):
        response = self.client.get("/")
        session_key = response.wsgi_request.session.session_key
        SearchHistory.objects.create(
            session_key=session_key,
            query_text="CSE students",
            filters={"_keyword": "CSE students"},
            result_count=2,
        )

        response = self.client.get("/")

        self.assertContains(response, "Search history")
        self.assertContains(response, "CSE students")
        self.assertContains(response, "2 result(s)")

    @patch("records.views.build_queryset")
    @patch("records.views.ask_ai", return_value={})
    def test_new_search_is_shown_in_sidebar(self, ask_ai, build_queryset):
        build_queryset.return_value.count.return_value = 0

        response = self.client.get("/", {"q": "biology"})

        self.assertContains(response, "biology")
        self.assertEqual(response.context["search_history"].count(), 1)

    def test_history_entry_can_be_deleted_only_by_its_session(self):
        self.client.get("/")
        session_key = self.client.session.session_key
        item = SearchHistory.objects.create(
            session_key=session_key,
            query_text="biology",
            filters={"_keyword": "biology"},
        )

        response = self.client.post(f"/history/{item.id}/delete/")

        self.assertRedirects(response, "/history/")
        self.assertFalse(SearchHistory.objects.filter(id=item.id).exists())

    def test_history_entry_cannot_be_deleted_with_get(self):
        self.client.get("/")
        item = SearchHistory.objects.create(
            session_key=self.client.session.session_key,
            query_text="biology",
            filters={"_keyword": "biology"},
        )

        response = self.client.get(f"/history/{item.id}/delete/")

        self.assertEqual(response.status_code, 405)
        self.assertTrue(SearchHistory.objects.filter(id=item.id).exists())

    def test_history_entry_cannot_be_deleted_from_another_session(self):
        self.client.get("/")
        item = SearchHistory.objects.create(
            session_key=self.client.session.session_key,
            query_text="biology",
            filters={"_keyword": "biology"},
        )
        other_client = Client()
        other_client.get("/")

        response = other_client.post(f"/history/{item.id}/delete/")

        self.assertEqual(response.status_code, 404)
        self.assertTrue(SearchHistory.objects.filter(id=item.id).exists())


class PersonManagementTests(TestCase):
    def test_add_person_saves_student_details(self):
        response = self.client.post(
            "/people/add/",
            {
                "person_type": "student",
                "name": "Ravi Kumar",
                "status": "active",
            },
        )

        self.assertRedirects(response, "/people/add/")
        person = Person.objects.get(name="Ravi Kumar")
        self.assertEqual(person.person_type, "student")

    def test_add_person_saves_candidate_details(self):
        response = self.client.post(
            "/people/add/",
            {
                "person_type": "candidate",
                "name": "Asha Patel",
                "email": "asha@example.com",
                "phone": "1234567890",
                "department": "Science",
                "course": "",
                "year": "",
                "designation": "Research candidate",
                "status": "active",
            },
        )

        self.assertRedirects(response, "/people/add/")
        person = Person.objects.get(name="Asha Patel")
        self.assertEqual(person.person_type, "candidate")
        self.assertEqual(person.email, "asha@example.com")

    def test_add_person_rejects_missing_name(self):
        response = self.client.post(
            "/people/add/",
            {"person_type": "student", "name": ""},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Person.objects.exists())
        self.assertContains(response, "This field is required.")

    def test_remove_page_deletes_person_only_on_post(self):
        person = Person.objects.create(person_type="student", name="Ravi")
        remove_page = self.client.get("/people/remove/")
        self.assertContains(remove_page, "Ravi")

        get_response = self.client.get(f"/people/{person.id}/delete/")
        self.assertEqual(get_response.status_code, 405)
        self.assertTrue(Person.objects.filter(id=person.id).exists())

        post_response = self.client.post(f"/people/{person.id}/delete/")
        self.assertRedirects(post_response, "/people/remove/")
        self.assertFalse(Person.objects.filter(id=person.id).exists())

    def test_person_details_can_be_edited(self):
        person = Person.objects.create(
            person_type="student",
            name="Ravi",
            email="ravi@example.com",
        )

        response = self.client.post(
            f"/people/{person.id}/edit/",
            {
                "person_type": "candidate",
                "name": "Ravi Kumar",
                "email": "ravi.kumar@example.com",
                "status": "active",
            },
        )

        self.assertRedirects(response, "/people/remove/")
        person.refresh_from_db()
        self.assertEqual(person.name, "Ravi Kumar")
        self.assertEqual(person.person_type, "candidate")
        self.assertEqual(person.email, "ravi.kumar@example.com")


class PeopleFileUploadTests(TestCase):
    def test_csv_search_matches_uploaded_names_and_emails(self):
        Person.objects.create(
            person_type="candidate",
            name="Asha Patel",
            email="asha@example.com",
        )
        upload = SimpleUploadedFile(
            "search.csv",
            b"name,email\nAsha Patel,asha@example.com\n",
        )

        response = self.client.post(
            "/search/upload/",
            {"upload_file": upload},
        )

        self.assertContains(response, "Asha Patel")
        self.assertContains(response, "File match")
        self.assertEqual(response.context["result_count"], 1)

    def test_import_skips_existing_and_repeated_email_addresses(self):
        Person.objects.create(
            person_type="student",
            name="Existing Student",
            email="existing@example.com",
        )
        upload = SimpleUploadedFile(
            "people.csv",
            (
                b"person_type,name,email\n"
                b"student,Existing Duplicate,EXISTING@example.com\n"
                b"candidate,New Candidate,new@example.com\n"
                b"student,Repeated Email,new@example.com\n"
            ),
        )

        response = self.client.post(
            "/people/import/",
            {"upload_file": upload, "person_type": "student"},
            follow=True,
        )

        self.assertContains(response, "Imported 1 person record")
        self.assertContains(response, "Skipped 2 record")
        self.assertEqual(Person.objects.count(), 2)
        self.assertTrue(Person.objects.filter(name="New Candidate").exists())

    def test_invalid_import_does_not_save_valid_rows_partially(self):
        upload = SimpleUploadedFile(
            "people.csv",
            b"person_type,name\nstudent,Valid Student\nunknown,Invalid Type\n",
        )

        response = self.client.post(
            "/people/import/",
            {"upload_file": upload, "person_type": "student"},
            follow=True,
        )

        self.assertContains(response, "No records were saved.")
        self.assertEqual(Person.objects.count(), 0)

    def test_import_uses_selected_category_only_when_file_omits_it(self):
        upload = SimpleUploadedFile(
            "people.csv",
            (
                b"name,email,person_type\n"
                b"Missing Type,missing@example.com,\n"
                b"Existing Type,existing@example.com,employee\n"
            ),
        )

        response = self.client.post(
            "/people/import/",
            {"upload_file": upload, "person_type": "candidate"},
            follow=True,
        )

        self.assertContains(response, "Imported 2 person record")
        self.assertEqual(
            Person.objects.get(name="Missing Type").person_type,
            "candidate",
        )
        self.assertEqual(
            Person.objects.get(name="Existing Type").person_type,
            "employee",
        )

    def test_json_upload_is_normalized_to_person_fields(self):
        upload = SimpleUploadedFile(
            "people.json",
            b'{"people":[{"type":"Candidate","full_name":"Mina Lee",'
            b'"email_address":"mina@example.com"}]}',
        )

        records = parse_people_upload(upload)

        self.assertEqual(
            records,
            [{
                "person_type": "candidate",
                "name": "Mina Lee",
                "email": "mina@example.com",
                "status": "active",
            }],
        )

    def test_xlsx_table_is_parsed(self):
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.append(["Type", "Name", "Email"])
        worksheet.append(["student", "Ravi Kumar", "ravi@example.com"])
        content = io.BytesIO()
        workbook.save(content)
        upload = SimpleUploadedFile("people.xlsx", content.getvalue())

        records = parse_people_upload(upload)

        self.assertEqual(records[0]["person_type"], "student")
        self.assertEqual(records[0]["name"], "Ravi Kumar")
        self.assertEqual(records[0]["email"], "ravi@example.com")

    def test_labeled_text_upload_is_parsed(self):
        upload = SimpleUploadedFile(
            "people.txt",
            (
                b"Type: student\nName: Noor Khan\n"
                b"Email: noor@example.com\n\n"
                b"Type: candidate\nName: Kai Chen\n"
            ),
        )

        records = parse_people_upload(upload)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["name"], "Noor Khan")
        self.assertEqual(records[1]["person_type"], "candidate")

    def test_docx_table_is_parsed(self):
        document = Document()
        table = document.add_table(rows=2, cols=3)
        for cell, value in zip(
            table.rows[0].cells, ["Type", "Name", "Email"]
        ):
            cell.text = value
        for cell, value in zip(
            table.rows[1].cells,
            ["candidate", "Sam Rivera", "sam@example.com"],
        ):
            cell.text = value
        content = io.BytesIO()
        document.save(content)
        upload = SimpleUploadedFile("people.docx", content.getvalue())

        records = parse_people_upload(upload)

        self.assertEqual(records[0]["name"], "Sam Rivera")
        self.assertEqual(records[0]["person_type"], "candidate")

    def test_text_pdf_is_parsed(self):
        content = io.BytesIO()
        pdf = canvas.Canvas(content, pagesize=letter)
        pdf.drawString(40, 740, "Type: student")
        pdf.drawString(40, 720, "Name: Isha Shah")
        pdf.drawString(40, 700, "Email: isha@example.com")
        pdf.save()
        upload = SimpleUploadedFile("people.pdf", content.getvalue())

        records = parse_people_upload(upload)

        self.assertEqual(records[0]["name"], "Isha Shah")
        self.assertEqual(records[0]["email"], "isha@example.com")

    @patch("records.file_uploads.shutil.which", return_value=None)
    def test_image_upload_reports_missing_local_ocr(self, _which):
        upload = SimpleUploadedFile("people.png", b"image bytes")
        self.assertIsNone(_which.return_value)

        with self.assertRaisesMessage(UploadFileError, "Tesseract"):
            parse_people_upload(upload)

    def test_upload_rejects_files_over_size_limit(self):
        upload = SimpleUploadedFile(
            "people.csv",
            b"x" * (MAX_UPLOAD_SIZE + 1),
        )

        with self.assertRaisesMessage(UploadFileError, "5 MB"):
            parse_people_upload(upload)
