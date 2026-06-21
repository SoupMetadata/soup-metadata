#!/bin/bash

# Initialize variables
s_flag=false

# Parse command-line options
while getopts "stp" opt; do
	case $opt in
		p)
			p_flag=true
			;;
		\?)
			echo "Invalid option: -$OPTARG" >&2
			exit 1
			;;
	esac
done

poetry run python3 scripts/update_patreon.py > /dev/null
poetry run python3 scripts/update_royalroad.py > /dev/null
poetry run python3 scripts/intermediary.py > /dev/null

# Use the flags
if $p_flag; then
	echo "Option -p is set, showing plots..."
	poetry run python3 scripts/plot_patreon.py -p
fi
