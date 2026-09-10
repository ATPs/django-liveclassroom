from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model

from liveclassroom.services.classroom import create_activity_definition
from liveclassroom.services.sharing import ContentShareError, create_share, list_shares, revoke_share, shared_resource


@pytest.mark.django_db
def test_named_question_share_is_exact_idempotent_and_revocable():
    users = get_user_model()
    owner = users.objects.create_user(username=f"share-o-{uuid4()}")
    recipient = users.objects.create_user(username=f"share-r-{uuid4()}")
    stranger = users.objects.create_user(username=f"share-s-{uuid4()}")
    question = create_activity_definition(owner=owner, title="Q", type_key="short_text", definition={"prompt": "Q"})
    share = create_share(actor=owner, kind="question", object_id=question.pk, recipient=recipient)
    assert create_share(actor=owner, kind="question", object_id=question.pk, recipient=recipient).pk == share.pk
    assert shared_resource(actor=recipient, share=share).pk == question.pk
    with pytest.raises(ContentShareError):
        shared_resource(actor=stranger, share=share)
    assert list(list_shares(actor=owner)) == [share]
    revoke_share(actor=owner, share=share)
    with pytest.raises(ContentShareError):
        shared_resource(actor=recipient, share=share)


@pytest.mark.django_db
def test_recipient_copy_is_an_independent_owned_question_and_revocation_preserves_it():
    users = get_user_model()
    owner = users.objects.create_user(username=f"share-copy-owner-{uuid4()}")
    recipient = users.objects.create_user(username=f"share-copy-recipient-{uuid4()}")
    source = create_activity_definition(
        owner=owner,
        title="Source question",
        type_key="short_text",
        definition={"prompt": "Name one organ."},
    )
    share = create_share(actor=owner, kind="question", object_id=source.pk, recipient=recipient)

    from liveclassroom.services.sharing import copy_shared_content

    copied = copy_shared_content(actor=recipient, share=share).activities[0]
    assert copied.owner_id == recipient.pk
    assert copied.pk != source.pk
    assert copied.current_revision.payload == source.current_revision.payload
    copied.title = "Recipient copy"
    copied.save()
    source.title = "Changed source"
    source.save()
    copied.refresh_from_db()
    assert copied.title == "Recipient copy"

    revoke_share(actor=owner, share=share)
    with pytest.raises(ContentShareError):
        copy_shared_content(actor=recipient, share=share)
    assert copied.owner_id == recipient.pk


@pytest.mark.django_db
def test_share_copy_refuses_a_dependency_owned_by_someone_else():
    users = get_user_model()
    owner = users.objects.create_user(username=f"share-owner-{uuid4()}")
    recipient = users.objects.create_user(username=f"share-recipient-{uuid4()}")
    foreign_owner = users.objects.create_user(username=f"share-foreign-{uuid4()}")
    source = create_activity_definition(owner=owner, title="Source", type_key="short_text", definition={"prompt": "Q"})
    foreign = create_activity_definition(
        owner=foreign_owner,
        title="Foreign question",
        type_key="short_text",
        definition={"prompt": "Do not copy"},
    )
    from liveclassroom.services.question_banks import add_question_to_bank, create_question_bank
    from liveclassroom.services.sharing import copy_shared_content

    bank = create_question_bank(actor=owner, data={"title": "Mixed bank"})
    add_question_to_bank(actor=owner, bank=bank, definition=source)
    # Direct historical/administrative corruption must fail closed during copy.
    bank.items.create(definition=foreign, position=2)
    share = create_share(actor=owner, kind="bank", object_id=bank.pk, recipient=recipient)
    with pytest.raises(ContentShareError, match="private dependency"):
        copy_shared_content(actor=recipient, share=share)


@pytest.mark.django_db
def test_content_share_api_hides_source_text_and_enforces_owner_recipient(client):
    import json

    from django.urls import reverse

    users = get_user_model()
    owner = users.objects.create_user(username=f"share-api-owner-{uuid4()}")
    recipient = users.objects.create_user(username=f"share-api-recipient-{uuid4()}")
    stranger = users.objects.create_user(username=f"share-api-stranger-{uuid4()}")
    source = create_activity_definition(
        owner=owner,
        title="Private source",
        type_key="short_text",
        definition={"prompt": "secret source text"},
    )
    collection = reverse("liveclassroom:api-v1-content-shares")
    client.force_login(owner)
    created = client.post(
        collection,
        data=json.dumps({"kind": "question", "object_id": source.pk, "recipient_id": recipient.pk}),
        content_type="application/json",
    )
    assert created.status_code == 201
    assert "secret source text" not in created.content.decode()
    share_id = created.json()["id"]
    assert client.get(collection).json()["content_shares"][0]["id"] == share_id

    client.force_login(stranger)
    assert client.post(reverse("liveclassroom:api-v1-content-share-copy", args=[share_id]), data="{}", content_type="application/json").status_code == 404

    client.force_login(recipient)
    copied = client.post(reverse("liveclassroom:api-v1-content-share-copy", args=[share_id]), data="{}", content_type="application/json")
    assert copied.status_code == 201
    assert copied.json()["objects"] == [{"kind": "activity", "id": copied.json()["objects"][0]["id"], "title": "Private source"}]
    assert client.delete(reverse("liveclassroom:api-v1-content-share-detail", args=[share_id])).status_code == 403

    client.force_login(owner)
    assert client.delete(reverse("liveclassroom:api-v1-content-share-detail", args=[share_id])).status_code == 200
    client.force_login(recipient)
    assert client.post(reverse("liveclassroom:api-v1-content-share-copy", args=[share_id]), data="{}", content_type="application/json").status_code == 403
