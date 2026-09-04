from sqlmodel import SQLModel

import app.models  # noqa: F401  ensures all models are registered on the metadata
from app.db.session import engine


def create_all() -> None:
    SQLModel.metadata.create_all(engine)


if __name__ == "__main__":
    create_all()
    print("Database schema created.")
