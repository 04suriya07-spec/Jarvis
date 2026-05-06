.PHONY: install start stop status restart test logs

install:
	bash install.sh

start:
	sudo systemctl start javris.service

stop:
	sudo systemctl stop javris.service

status:
	sudo systemctl status javris.service

restart:
	sudo systemctl restart javris.service

logs:
	sudo journalctl -u javris.service -f

test:
	python3 -m pytest tests/ -q
