"""phase2: RAG knowledge base + agent reasoning tables

Revision ID: a1b2c3d4e5f6
Revises: bec05e4fe071
Create Date: 2026-08-03 20:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "bec05e4fe071"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sys_feature_flag",
        sa.Column("flag_key", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.ForeignKeyConstraint(["updated_by"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "kb_document",
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("file_url", sa.String(length=512), nullable=True),
        sa.Column("file_sha256", sa.String(length=64), nullable=True),
        sa.Column("mime_type", sa.String(length=64), nullable=True),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("doc_key", sa.String(length=64), nullable=False),
        sa.Column("status", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("parse_error", sa.String(length=512), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=True),
        sa.Column("embedding_model", sa.String(length=64), nullable=True),
        sa.Column("uploaded_by", sa.BigInteger(), nullable=True),
        sa.Column("reviewed_by", sa.BigInteger(), nullable=True),
        sa.Column("published_by", sa.BigInteger(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("meta_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.ForeignKeyConstraint(["published_by"], ["sys_user.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["sys_user.id"]),
        sa.ForeignKeyConstraint(["uploaded_by"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_kb_document_category_status", "kb_document", ["category", "status"]
    )
    op.create_index(
        "ix_kb_document_doc_key_version", "kb_document", ["doc_key", "version"]
    )

    op.create_table(
        "kb_chunk",
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("doc_version", sa.Integer(), nullable=False),
        sa.Column("is_published", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("vector_id", sa.String(length=64), nullable=True),
        sa.Column("meta_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["kb_document.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_kb_chunk_published_category", "kb_chunk", ["is_published", "category"]
    )
    op.create_index(
        "ix_kb_chunk_document_index", "kb_chunk", ["document_id", "chunk_index"]
    )

    op.create_table(
        "kb_publish_log",
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("doc_key", sa.String(length=64), nullable=False),
        sa.Column("from_document_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("operator_id", sa.BigInteger(), nullable=True),
        sa.Column("remark", sa.String(length=512), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["document_id"], ["kb_document.id"]),
        sa.ForeignKeyConstraint(["operator_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "kb_blind_spot",
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("advisor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("customer_id", sa.BigInteger(), nullable=True),
        sa.Column("conversation_id", sa.BigInteger(), nullable=True),
        sa.Column("suggestion_event_id", sa.BigInteger(), nullable=True),
        sa.Column("top_score", sa.Numeric(precision=6, scale=4), nullable=True),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("status", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.ForeignKeyConstraint(["advisor_user_id"], ["sys_user.id"]),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["customer.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "agent_run",
        sa.Column("conversation_id", sa.BigInteger(), nullable=True),
        sa.Column("customer_id", sa.BigInteger(), nullable=True),
        sa.Column("advisor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("suggestion_event_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("user_question", sa.Text(), nullable=False),
        sa.Column("plan_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("final_text", sa.Text(), nullable=True),
        sa.Column("sources_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "uncertainty_notes_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("confidence", sa.Numeric(precision=3, scale=2), nullable=True),
        sa.Column("step_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_steps", sa.Integer(), server_default="3", nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=32), nullable=True),
        sa.Column("error_message", sa.String(length=512), nullable=True),
        sa.Column("model_version", sa.String(length=32), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.ForeignKeyConstraint(["advisor_user_id"], ["sys_user.id"]),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversation.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["customer.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_run_advisor_created", "agent_run", ["advisor_user_id", "created_at"]
    )

    op.create_table(
        "agent_step",
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("phase", sa.String(length=32), nullable=False),
        sa.Column("capability", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=128), nullable=True),
        sa.Column("input_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("output_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "source_refs_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("status", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["agent_run.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_step_run_index", "agent_step", ["run_id", "step_index"])

    op.create_table(
        "agent_feedback",
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("suggestion_event_id", sa.BigInteger(), nullable=True),
        sa.Column("advisor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("rating", sa.SmallInteger(), nullable=True),
        sa.Column("is_negative", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("comment", sa.String(length=1024), nullable=True),
        sa.Column("issue_tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.ForeignKeyConstraint(["advisor_user_id"], ["sys_user.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["agent_run.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "advisor_notification",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("body", sa.String(length=512), nullable=True),
        sa.Column("ref_type", sa.String(length=32), nullable=True),
        sa.Column("ref_id", sa.BigInteger(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["sys_user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_advisor_notification_user",
        "advisor_notification",
        ["user_id", "created_at"],
    )

    op.add_column(
        "suggestion_event",
        sa.Column("mode", sa.String(length=16), server_default="legacy", nullable=True),
    )
    op.add_column(
        "suggestion_event", sa.Column("agent_run_id", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "suggestion_event",
        sa.Column("fallback", sa.Boolean(), server_default="false", nullable=True),
    )
    op.add_column(
        "suggestion_event",
        sa.Column(
            "citations_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )
    op.add_column(
        "suggestion_event",
        sa.Column(
            "uncertainty_notes_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )

    op.execute(
        """
        INSERT INTO sys_feature_flag (flag_key, enabled, description)
        VALUES
          ('agent_reasoning_enabled', true, '综合推理增强总开关'),
          ('kb_rag_enabled', true, '知识库 RAG 开关')
        """
    )


def downgrade() -> None:
    op.drop_column("suggestion_event", "uncertainty_notes_json")
    op.drop_column("suggestion_event", "citations_json")
    op.drop_column("suggestion_event", "fallback")
    op.drop_column("suggestion_event", "agent_run_id")
    op.drop_column("suggestion_event", "mode")

    op.drop_index("ix_advisor_notification_user", table_name="advisor_notification")
    op.drop_table("advisor_notification")
    op.drop_table("agent_feedback")
    op.drop_index("ix_agent_step_run_index", table_name="agent_step")
    op.drop_table("agent_step")
    op.drop_index("ix_agent_run_advisor_created", table_name="agent_run")
    op.drop_table("agent_run")
    op.drop_table("kb_blind_spot")
    op.drop_table("kb_publish_log")
    op.drop_index("ix_kb_chunk_document_index", table_name="kb_chunk")
    op.drop_index("ix_kb_chunk_published_category", table_name="kb_chunk")
    op.drop_table("kb_chunk")
    op.drop_index("ix_kb_document_doc_key_version", table_name="kb_document")
    op.drop_index("ix_kb_document_category_status", table_name="kb_document")
    op.drop_table("kb_document")
    op.drop_table("sys_feature_flag")
