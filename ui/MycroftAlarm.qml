        // Copyright 2021, Mycroft AI Inc.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//    http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

import QtQuick 2.4
import QtQuick.Layouts 1.1
import QtQuick.Controls 2.3

Rectangle {
    property color backgroundColor
    property var alarmInfo
    property int alarmCount

    color: alarmInfo ? backgroundColor : "transparent"
    height: alarmCount <= 2 ? gridUnit * 26 : gridUnit * 12
    radius: 16
    width: alarmCount === 1 ? gridUnit * 46 : gridUnit * 22

    /* Flash the background when the alarm expires for a visual cue */
    SequentialAnimation on opacity {
        id: expireAnimation
        running: alarmInfo ? alarmInfo.expired : false
        loops: Animation.Infinite
        PropertyAnimation {
            from: 1;
            to: 0.25;
            duration: 500
        }
        PropertyAnimation {
            from: 0.25;
            to: 1;
            duration: 500
        }
    }

    Item {
        id: alarmName
        anchors.top: parent.top
        height: alarmCount <= 2 ? gridUnit * 4 : gridUnit * 3
        width: parent.width

        AlarmLabel {
            id: alarmNameValue
            anchors.top: parent.top
            anchors.topMargin: gridUnit
            anchors.horizontalCenter: parent.horizontalCenter
            color: "#2C3E50"
            font.pixelSize: alarmCount === 1 ? 47 : 35
            font.styleName: "Bold"
            heightUnits: 5
            text: alarmInfo ? alarmInfo.alarmName : ""
            maxTextLength: width / 30
        }
    }

    // The alarm clock icon is positioned in the upper left corner of the rectangle
    // when the screen is split in to quadrants.  When screen is split in half or
    // not at all, the icon appears under the alarm name.
    Image {
        id: alarmClockImage
        anchors.top: alarmCount >= 3 ? parent.top : alarmName.bottom
        anchors.topMargin: alarmCount >= 3 ? gridUnit : gridUnit * 2
        anchors.left: parent.left
        anchors.leftMargin: alarmCount >= 3 ? gridUnit : 0
        anchors.horizontalCenter: alarmCount >= 3 ? undefined : parent.horizontalCenter
        opacity: alarmInfo ? 1.0 : 0.0
        fillMode: Image.PreserveAspectFit
        height: alarmCount >= 3 ? gridUnit * 2 : gridUnit * 7
        source: "images/alarm-clock.svg"
    }

    Item {
        id: alarmTime
        anchors.top: alarmClockImage.bottom
        height: {
            if (alarmCount === 1) {
                return gridUnit * 7
            } else if (alarmCount === 2) {
                return gridUnit * 6
            } else {
                return gridUnit * 4
            }
        }
        width: parent.width

        Label {
            id: alarmTimeValue
            anchors.baseline: parent.bottom
            anchors.horizontalCenter: parent.horizontalCenter
            font.pixelSize: alarmCount === 1 ? 118 : 59
            font.styleName: "Bold"
            text: alarmInfo ? alarmInfo.alarmTime : ""
        }
    }

    Item {
        id: alarmDate
        anchors.top: alarmTime.bottom
        height: {
            if (alarmCount === 1) {
                return gridUnit * 4
            } else if (alarmCount === 2) {
                return gridUnit * 5
            } else {
                return gridUnit * 3
            }
        }
        width: parent.width

        Label {
            id: alarmDateValue
            anchors.baseline: parent.bottom
            anchors.horizontalCenter: parent.horizontalCenter
            color: "#2C3E50"
            font.pixelSize: alarmCount === 1 ? 35 : 24
            font.styleName: "Normal"
            text: alarmInfo ? alarmInfo.alarmDays : ""
        }
    }
}
