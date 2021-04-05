# Import required libraries.
import csv
import os
from time import time, sleep
import datetime

# Convert unix time to real time.
def convertTime(unixTime):
    try:
        realTime =  datetime.datetime.fromtimestamp(int(unixTime)/1000).strftime("%H:%M:%S")
    except ValueError:
        return unixTime
    return realTime

# User defined variables.
httpCode = "200"        # Only collect data with the HTTP code defined here.
averagePoints = 100     # How many items should we use for each average.

# Create a directory to work in to prevent accidental data loss.
curTime = str(time())
os.mkdir("./csvtoolspy-" + curTime)
os.chdir("./csvtoolspy-" + curTime)
print("Now working in " + os.getcwd())

# Sleep to give the user a chance to notice possible direcotry issues.
sleep(2)

# Define the lists to use.
# Do not reorder these lists or values may go out of sync.
allThreads = []
responseCodes = []

# Populate the lists with number of active threads and the response code for that request.
with open('../results.csv', mode='r') as rawFile:
    reader = csv.reader(rawFile)
    for row in reader:
        if row[3] == "responseCode":
            continue
        try:
            allThreads.append(int(row[12]))
            responseCodes.append(row[3])
        except ValueError:
            continue

# Print the length of these lists for debugging.
print(len(allThreads))
print(len(responseCodes))

# Get the min and max values for threads.
minThreads = min(allThreads)
maxThreads = max(allThreads)

# Create a range to loop through using these values.
loopRange = range(int(minThreads), int(maxThreads) + 1)

# For each unique value for active threads, calculate the percentage of requests that recieved an error response.
with open('errors.csv', mode='w+') as errorOutputFile:
    writer = csv.writer(errorOutputFile)
    writer.writerow(["errorThreads", "errors", "successes", "percentErrors"])
    for i in loopRange:
        indexes = [index for index, value in enumerate(allThreads) if value == i]
        numErrors = 0
        numSuccess = 0
        for index in indexes:
            if responseCodes[index] == "200":
                print("200 - OK")
                numSuccess = numSuccess + 1
            else:
                print("Found Error: " + str(responseCodes[index]))
                numErrors = numErrors + 1
        try:
            percentErrors = (numErrors / (numSuccess + numErrors) * 100)
        except ZeroDivisionError:
            pass
        writer.writerow([i, numErrors, numSuccess, percentErrors])
        print(str(i) + ":" + str(numErrors) + ":" + str(numSuccess) + "-" + str(percentErrors) + "%")

# Clear out lists for following code.
allThreads = []
elapsed = []

# Open the raw Jmeter CSV for reading.
with open('../results.csv', mode='r') as rawFile:
    reader = csv.reader(rawFile)
    # Write out a CSV with the subset of raw data we want to work with.
    with open('raw.csv', mode='w+') as rawOutputFile:
        writer = csv.writer(rawOutputFile)
        # Write out column headers as they will be removed by the next step.
        writer.writerow(["time", "elapsed", "allThreads"])
        print("About to discard any rows where HTTP code does not equal " + str(httpCode))
        for row in reader:
            # Discard rows with a HTTP response code other than 200.
            if row[3] != str(httpCode):
                with open('./rawErrors.csv', mode='w+') as rawErrorFile:
                    errorWriter = csv.writer(rawErrorFile)
                    errorWriter.writerow([str(convertTime(row[0])), row[1]])
                continue
            else:
                # Write out the "time", "allThreads" and "elapsed" columns of the rows that are left.
                writer.writerow([str(convertTime(row[0])), row[1], row[12]])


# Open the CSV we just created and re-calculate the min and max thread values.
with open('raw.csv', mode='r') as tempFile:
    reader = csv.reader(tempFile)
    for row in reader:
        try:
            allThreads.append(int(row[2]))
            elapsed.append(int(row[1]))
        except ValueError:
            continue

# Get the min and max values for threads.
minThreads = min(allThreads)
maxThreads = max(allThreads)

# Create a range to loop through.
loopRange = range(minThreads, maxThreads + 1)

# Print the range for debugging
print(loopRange)

# Write out averages to a new CSV file.
with open('averageResponseTime.csv', mode='w+') as outputFile:
    writer = csv.writer(outputFile)
    writer.writerow(["average", "aveThreads"])
    i = 1
    while i < len(loopRange):
        # Get all indexes in allThreads with our current value for i.
        indexes = []
        for j in range(i, (i+averagePoints)):
            indexes.extend([index for index, value in enumerate(allThreads) if value == i])

        # Average the same indexes in elapsed.
        values = []
        for index in indexes:
            print(str(allThreads[index]) + ": " + str(elapsed[index]))
            values.append(elapsed[index])
        try:
            ave = sum(values) / len(values)
            print(ave)
            writer.writerow([i,ave])
            print("Written to CSV")
        except ZeroDivisionError:
            pass
        i = i+averagePoints