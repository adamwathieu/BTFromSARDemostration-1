import argparse
import json
import os
import csv
import pandas as pd
from json_manager import JsonManager
import pipeline_constants as constants
# from queue import Queue

CSV_EXTENSIONS = (".csv", ".CSV")
CSV_NAME_EXTENSION = "_normalized"

def is_file_CSV(filename):
	return filename.endswith(CSV_EXTENSIONS)

# Description: takes parameter original_filename and adds extension to name
# ex: original_filename = "helloWorld.txt", extension = "_addMe"
# return: helloWorld_addMe.txt
def make_modified_filename(original_filename, extension):
	filename_root, filename_ext = os.path.splitext(\
		os.path.basename(original_filename))
	return filename_root + extension + filename_ext

# Description: updates the 2D queue all_lag_queues at index index with the value value
# returns the first thing in the queue that isnt empty, else returns ''
def update_lag_feature_queue(lag_feature_queue, value):
	lag_feature_queue.append(value)
	lag_feature_queue.pop(0)
	return next((time_step for time_step in lag_feature_queue if time_step), '')

def process_command_line_args():
	ap = argparse.ArgumentParser()
	ap.add_argument("-config", "--configuration", \
		required = True, \
		help = "Path to the configuration file")
	args = vars(ap.parse_args())
	return args["configuration"]

def main():
	json_file_path = process_command_line_args()
	json_manager = JsonManager(json_file_path)

	csv_folder = json_manager.get_csv_path()
	normalized_folder = json_manager.get_normalized_path()
	feature_columns = json_manager.get_feature_columns()
	label_columns = json_manager.get_label_columns()
	lag_features = json_manager.get_lag_features()
	lag_window_length = json_manager.get_sliding_window_length()

	destination_path = constants.add_folder_to_directory(\
		constants.NORMALIZED_CSV_FOLDER_NAME, normalized_folder)

	for file in os.listdir(csv_folder):
		complete_file_path = os.fsdecode(os.path.join(csv_folder, file))

		if is_file_CSV(file):
			normalized_filename = make_modified_filename(\
				file, CSV_NAME_EXTENSION)
			normalized_file_path = os.fsdecode(os.path.join(\
				destination_path, normalized_filename))

			current_csv_obj = open(complete_file_path)
			normalized_csv_obj = open(normalized_file_path, mode='w')

			csv_reader = csv.reader(current_csv_obj, \
				delimiter = constants.CSV_DELIMITER)
			csv_writer = csv.writer(normalized_csv_obj, \
				delimiter = constants.CSV_DELIMITER, \
				quotechar = constants.CSV_QUOTECHAR, \
				quoting=csv.QUOTE_MINIMAL)

			all_lag_queues = [[""] * lag_window_length for lag_feature in lag_features]
			
			header_row = list(feature_columns)
			header_row.append(constants.LABEL_COLUMN_NAME)
			csv_writer.writerow(header_row)

			label_indices = list(label_columns.values())
			header_row_being_read = True
			for timeseries_row in csv_reader:
				if header_row_being_read:
					header_row_being_read = False
					continue
				label_values = [timeseries_row[index] for index in label_indices]
				label_value = next((label_value for label_value in label_values \
					if label_value), None)

				if label_value:
					new_normalize_row = []
					for column_name, column_index in feature_columns.items():
						if column_name in lag_features:
							index = lag_features.index(column_name)
							lagged_feature = update_lag_feature_queue(\
								all_lag_queues[index], timeseries_row[column_index])
							new_normalize_row.append(lagged_feature)
						else:
							new_normalize_row.append(\
								timeseries_row[feature_columns[column_name]])
					new_normalize_row.append(label_value)
					csv_writer.writerow(new_normalize_row)
				else: 
					for column_index, column_name in enumerate(lag_features):
						value = timeseries_row[feature_columns[column_name]]
						update_lag_feature_queue(all_lag_queues[column_index], value)

			current_csv_obj.close()
			normalized_csv_obj.close()

	combined_csv_file_path = os.path.join(destination_path, constants.COMBINED_CSV_FILENAME)

	if os.path.exists(combined_csv_file_path): 
		os.remove(combined_csv_file_path)
	combined_csv = pd.concat([pd.read_csv(os.fsdecode(os.path.join(destination_path, f)))\
		for f in os.listdir(destination_path)])
	combined_csv.to_csv( os.fsdecode(combined_csv_file_path), \
		index = False, encoding = 'utf-8-sig')


if __name__ == '__main__':
	main()

