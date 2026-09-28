from sqlalchemy import select

from demo_app.db import Base, make_session_factory
from demo_app.models import Organization


def main() -> None:
    factory = make_session_factory()
    Base.metadata.create_all(factory.kw["bind"])
    with factory() as db:
        if db.scalar(select(Organization).where(Organization.name == "Example")) is None:
            db.add(Organization(name="Example"))
            db.commit()


if __name__ == "__main__":
    main()
