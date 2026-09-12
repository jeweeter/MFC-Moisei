"""Очистка HTML: именно на этих артефактах ломается наивный strip_tags."""
from app.ingest.html_clean import clean_html


def test_word_namespace_and_conditional_comments_are_removed():
    raw = (
        '<p class="MsoNormal">1.Документ, удостоверяющий личность.<o:p></o:p></p>'
        '<!--[if gte mso 9]><xml><o:OfficeDocumentSettings>'
        '<o:AllowPNG/></o:OfficeDocumentSettings></xml><![endif]-->'
        '<w:WordDocument><w:View>Normal</w:View></w:WordDocument>'
    )
    res = clean_html(raw)
    assert "Документ, удостоверяющий личность" in res.text
    for junk in ("mso", "OfficeDocument", "AllowPNG", "Normal"):
        assert junk not in res.text


def test_base64_images_are_dropped_but_links_kept():
    raw = (
        '1) Установить приложение по ссылке: <a href="https://goskey.ru/">Госключ</a>'
        '<div><img src="data:image/png;base64,' + "A" * 5000 + '"></div>'
        '<div>2) Обратиться в МФЦ</div>'
    )
    res = clean_html(raw)
    assert res.images_dropped == 1
    assert "base64" not in res.text
    assert len(res.text) < 200
    assert res.links == [{"href": "https://goskey.ru/", "title": "Госключ"}]


def test_entities_and_nbsp_are_decoded():
    res = clean_html('<p>Справка&nbsp;&quot;о&nbsp;доходах&quot;&amp;копия</p>')
    assert res.text == 'Справка "о доходах"&копия'


def test_list_markers_are_extracted_even_without_space():
    res = clean_html('<p>1.Заявление</p><p>2)Паспорт</p><li>- Копия</li>')
    kinds = [(b.kind, b.marker, b.text) for b in res.blocks]
    assert kinds == [
        ("list_item", "1.", "Заявление"),
        ("list_item", "2)", "Паспорт"),
        ("list_item", "-", "Копия"),
    ]


def test_heading_detection_keeps_context_line():
    res = clean_html(
        "<p>Представитель дополнительно представляет:</p><p>- доверенность</p>"
    )
    assert res.blocks[0].kind == "heading"
    assert res.blocks[1].kind == "list_item"


def test_empty_and_none_input():
    assert clean_html(None).is_empty
    assert clean_html("").is_empty
    assert clean_html("   <p> </p>  ").is_empty


def test_plain_text_passes_through():
    assert clean_html("Бесплатно").text == "Бесплатно"
