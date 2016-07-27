#############################################################################
##
## Copyright (C) 2011 Riverbank Computing Limited.
## Copyright (C) 2006 Thorsten Marek.
## All right reserved.
##
## This file is part of PyQt.
##
## You may use this file under the terms of the GPL v2 or the revised BSD
## license as follows:
##
## "Redistribution and use in source and binary forms, with or without
## modification, are permitted provided that the following conditions are
## met:
##   * Redistributions of source code must retain the above copyright
##     notice, this list of conditions and the following disclaimer.
##   * Redistributions in binary form must reproduce the above copyright
##     notice, this list of conditions and the following disclaimer in
##     the documentation and/or other materials provided with the
##     distribution.
##   * Neither the name of the Riverbank Computing Limited nor the names
##     of its contributors may be used to endorse or promote products
##     derived from this software without specific prior written
##     permission.
##
## THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
## "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
## LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
## A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
## OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
## SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
## LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
## DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
## THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
## (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
## OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE."
##
#############################################################################


import sys
import logging
import os.path
import re

try:
    from xml.etree.ElementTree import parse, SubElement
except ImportError:
    try:
        from ElementTree import parse, SubElement
    except ImportError:
        try:
            from elementtree.ElementTree import parse, SubElement
        except ImportError:
            from PyQt4.elementtree.ElementTree import parse, SubElement


from PyQt4.uic.exceptions import NoSuchWidgetError
from PyQt4.uic.objcreator import QObjectCreator
from PyQt4.uic.properties import Properties


logger = logging.getLogger(__name__)
DEBUG = logger.debug

if sys.version_info < (2,4,0):
    def reversed(seq):
        for i in xrange(len(seq)-1, -1, -1):
            yield seq[i]

QtCore = None
QtGui = None


def gridPosition(elem):
    """gridPosition(elem) -> tuple

    Return the 4-tuple of (row, column, rowspan, colspan)
    for a widget element, or an empty tuple.
    """
    try:
        return (int(elem.attrib["row"]),
                int(elem.attrib["column"]),
                int(elem.attrib.get("rowspan", 1)),
                int(elem.attrib.get("colspan", 1)))
    except KeyError:
        return ()


class WidgetStack(list):
    topwidget = None
    def push(self, item):
        DEBUG("push %s %s" % (item.metaObject().className(),
                              item.objectName()))
        self.append(item)
        if isinstance(item, QtGui.QWidget):
            self.topwidget = item

    def popLayout(self):
        layout = list.pop(self)
        DEBUG("pop layout %s %s" % (layout.metaObject().className(),
                                    layout.objectName()))
        return layout

    def popWidget(self):
        widget = list.pop(self)
        DEBUG("pop widget %s %s" % (widget.metaObject().className(),
                                    widget.objectName()))
        for item in reversed(self):
            if isinstance(item, QtGui.QWidget):
                self.topwidget = item
                break
        else:
            self.topwidget = None
        DEBUG("new topwidget %s" % (self.topwidget,))
        return widget

    def peek(self):
        return self[-1]

    def topIsLayout(self):
        return isinstance(self[-1], QtGui.QLayout)


class UIParser(object):
    def __init__(self, QtCoreModule, QtGuiModule, creatorPolicy):
        self.factory = QObjectCreator(creatorPolicy)
        self.wprops = Properties(self.factory, QtCoreModule, QtGuiModule)

        global QtCore, QtGui
        QtCore = QtCoreModule
        QtGui = QtGuiModule

        self.reset()

    def uniqueName(self, name):
        """UIParser.uniqueName(string) -> string

        Create a unique name from a string.
        >>> p = UIParser(QtCore, QtGui)
        >>> p.uniqueName("foo")
        'foo'
        >>> p.uniqueName("foo")
        'foo1'
        """
        try:
            suffix = self.name_suffixes[name]
        except KeyError:
            self.name_suffixes[name] = 0
            return name

        suffix += 1
        self.name_suffixes[name] = suffix

        return "%s%i" % (name, suffix)

    def reset(self):
        try: self.wprops.reset()
        except AttributeError: pass
        self.toplevelWidget = None
        self.stack = WidgetStack()
        self.name_suffixes = {}
        self.defaults = {"spacing": 6, "margin": 0}
        self.actions = []
        self.currentActionGroup = None
        self.resources = []
        self.button_groups = []
        self.layout_widget = False

    def setupObject(self, clsname, parent, branch, is_attribute = True):
        name = self.uniqueName(branch.attrib.get("name") or clsname[1:].lower())
        if parent is None:
            args = ()
        else:
            args = (parent, )
        obj =  self.factory.createQObject(clsname, name, args, is_attribute)
        self.wprops.setProperties(obj, branch)
        obj.setObjectName(name)
        if is_attribute:
            setattr(self.toplevelWidget, name, obj)
        return obj

    def hasProperty(self, elem, name):
        for prop in elem.findall('property'):
            if prop.attrib['name'] == name:
                return True

        return False

    def createWidget(self, elem):
        self.column_counter = 0
        self.row_counter = 0
        self.item_nr = 0
        self.itemstack = []
        self.sorting_enabled = None

        widget_class = elem.attrib['class'].replace('::', '.')
        if widget_class == 'Line':
            widget_class = 'QFrame'

        # Ignore the parent if it is a container.
        parent = self.stack.topwidget
        if isinstance(parent, (QtGui.QDockWidget, QtGui.QMdiArea,
                               QtGui.QScrollArea, QtGui.QStackedWidget,
                               QtGui.QToolBox, QtGui.QTabWidget,
                               QtGui.QWizard)):
            parent = None

        # See if this is a layout widget.
        if widget_class == 'QWidget':
            if parent is not None:
                if not isinstance(parent, QtGui.QMainWindow):
                    self.layout_widget = True

        self.stack.push(self.setupObject(widget_class, parent, elem))

        if isinstance(self.stack.topwidget, QtGui.QTableWidget):
            if not self.hasProperty(elem, 'columnCount'):
                self.stack.topwidget.setColumnCount(len(elem.findall("column")))

            if not self.hasProperty(elem, 'rowCount'):
                self.stack.topwidget.setRowCount(len(elem.findall("row")))

        self.traverseWidgetTree(elem)
        widget = self.stack.popWidget()

        self.layout_widget = False

        if isinstance(widget, QtGui.QTreeView):
            self.handleHeaderView(elem, "header", widget.header())

        elif isinstance(widget, QtGui.QTableView):
            self.handleHeaderView(elem, "horizontalHeader",
                    widget.horizontalHeader())
            self.handleHeaderView(elem, "verticalHeader",
                    widget.verticalHeader())

        elif isinstance(widget, QtGui.QAbstractButton):
            bg_i18n = self.wprops.getAttribute(elem, "buttonGroup")
            if bg_i18n is not None:
                # This should be handled properly in case the problem arises
                # elsewhere as well.
                try:
                    # We are compiling the .ui file.
                    bg_name = bg_i18n.string
                except AttributeError:
                    # We are loading the .ui file.
                    bg_name = bg_i18n

                for bg in self.button_groups:
                    if bg.objectName() == bg_name:
                        break
                else:
                    bg = self.factory.createQObject("QButtonGroup", bg_name,
                            (self.toplevelWidget, ))
                    bg.setObjectName(bg_name)
                    self.button_groups.append(bg)

                bg.addButton(widget)

        if self.sorting_enabled is not None:
            widget.setSortingEnabled(self.sorting_enabled)
            self.sorting_enabled = None

        if self.stack.topIsLayout():
            lay = self.stack.peek()
            gp = elem.attrib["grid-position"]

            if isinstance(lay, QtGui.QFormLayout):
                lay.setWidget(gp[0], self._form_layout_role(gp), widget)
            else:
                lay.addWidget(widget, *gp)

        topwidget = self.stack.topwidget

        if isinstance(topwidget, QtGui.QToolBox):
            icon = self.wprops.getAttribute(elem, "icon")
            if icon is not None:
                topwidget.addItem(widget, icon, self.wprops.getAttribute(elem, "label"))
            else:
                topwidget.addItem(widget, self.wprops.getAttribute(elem, "label"))

            tooltip = self.wprops.getAttribute(elem, "toolTip")
            if tooltip is not None:
                topwidget.setItemToolTip(topwidget.indexOf(widget), tooltip)

        elif isinstance(topwidget, QtGui.QTabWidget):
            icon = self.wprops.getAttribute(elem, "icon")
            if icon is not None:
                topwidget.addTab(widget, icon, self.wprops.getAttribute(elem, "title"))
            else:
                topwidget.addTab(widget, self.wprops.getAttribute(elem, "title"))

            tooltip = self.wprops.getAttribute(elem, "toolTip")
            if tooltip is not None:
                topwidget.setTabToolTip(topwidget.indexOf(widget), tooltip)

        elif isinstance(topwidget, QtGui.QWizard):
            topwidget.addPage(widget)

        elif isinstance(topwidget, QtGui.QStackedWidget):
            topwidget.addWidget(widget)

        elif isinstance(topwidget, (QtGui.QDockWidget, QtGui.QScrollArea)):
            topwidget.setWidget(widget)

        elif isinstance(topwidget, QtGui.QMainWindow):
            if type(widget) == QtGui.QWidget:
                topwidget.setCentralWidget(widget)
            elif isinstance(widget, QtGui.QToolBar):
                tbArea = self.wprops.getAttribute(elem, "toolBarArea")

                if tbArea is None:
                    topwidget.addToolBar(widget)
                else:
                    topwidget.addToolBar(tbArea, widget)

                tbBreak = self.wprops.getAttribute(elem, "toolBarBreak")

                if tbBreak:
                    topwidget.insertToolBarBreak(widget)

            elif isinstance(widget, QtGui.QMenuBar):
                topwidget.setMenuBar(widget)
            elif isinstance(widget, QtGui.QStatusBar):
                topwidget.setStatusBar(widget)
            elif isinstance(widget, QtGui.QDockWidget):
                dwArea = self.wprops.getAttribute(elem, "dockWidgetArea")
                topwidget.addDockWidget(QtCore.Qt.DockWidgetArea(dwArea),
                        widget)

    def handleHeaderView(self, elem, name, header):
        value = self.wprops.getAttribute(elem, name + "Visible")
        if value is not None:
            header.setVisible(value)

        value = self.wprops.getAttribute(elem, name + "CascadingSectionResizes")
        if value is not None:
            header.setCascadingSectionResizes(value)

        value = self.wprops.getAttribute(elem, name + "DefaultSectionSize")
        if value is not None:
            header.setDefaultSectionSize(value)

        value = self.wprops.getAttribute(elem, name + "HighlightSections")
        if value is not None:
            header.setHighlightSections(value)

        value = self.wprops.getAttribute(elem, name + "MinimumSectionSize")
        if value is not None:
            header.setMinimumSectionSize(value)

        value = self.wprops.getAttribute(elem, name + "ShowSortIndicator")
        if value is not None:
            header.setSortIndicatorShown(value)

        value = self.wprops.getAttribute(elem, name + "StretchLastSection")
        if value is not None:
            header.setStretchLastSection(value)

    def createSpacer(self, elem):
        width = elem.findtext("property/size/width")
        height = elem.findtext("property/size/height")

        if width is None or height is None:
            size_args = ()
        else:
            size_args = (int(width), int(height))

        sizeType = self.wprops.getProperty(elem, "sizeType",
                QtGui.QSizePolicy.Expanding)

        policy = (QtGui.QSizePolicy.Minimum, sizeType)

        if self.wprops.getProperty(elem, "orientation") == QtCore.Qt.Horizontal:
            policy = policy[1], policy[0]

        spacer = self.factory.createQObject("QSpacerItem",
                self.uniqueName("spacerItem"), size_args + policy,
                is_attribute=False)

        if self.stack.topIsLayout():
            lay = self.stack.peek()
            gp = elem.attrib["grid-position"]

            if isinstance(lay, QtGui.QFormLayout):
                lay.setItem(gp[0], self._form_layout_role(gp), spacer)
            else:
                lay.addItem(spacer, *gp)

    def createLayout(self, elem):
        # Qt v4.3 introduced setContentsMargins() and separate values for each
        # of the four margins which are specified as separate properties.  This
        # doesn't really fit the way we parse the tree (why aren't the values
        # passed as attributes of a single property?) so we create a new
        # property and inject it.  However, if we find that they have all been
        # specified and have the same value then we inject a different property
        # that is compatible with older versions of Qt.
        left = self.wprops.getProperty(elem, 'leftMargin', -1)
        top = self.wprops.getProperty(elem, 'topMargin', -1)
        right = self.wprops.getProperty(elem, 'rightMargin', -1)
        bottom = self.wprops.getProperty(elem, 'bottomMargin', -1)

        # Count the number of properties and if they had the same value.
        def comp_property(m, so_far=-2, nr=0):
            if m >= 0:
                nr += 1

                if so_far == -2:
                    so_far = m
                elif so_far != m:
                    so_far = -1

            return so_far, nr

        margin, nr_margins = comp_property(left)
        margin, nr_margins = comp_property(top, margin, nr_margins)
        margin, nr_margins = comp_property(right, margin, nr_margins)
        margin, nr_margins = comp_property(bottom, margin, nr_margins)

        if nr_margins > 0:
            if nr_margins == 4 and margin >= 0:
                # We can inject the old margin property.
                me = SubElement(elem, 'property', name='margin')
                SubElement(me, 'number').text = str(margin)
            else:
                # We have to inject the new internal property.
                cme = SubElement(elem, 'property', name='pyuicContentsMargins')
                SubElement(cme, 'number').text = str(left)
                SubElement(cme, 'number').text = str(top)
                SubElement(cme, 'number').text = str(right)
                SubElement(cme, 'number').text = str(bottom)
        elif self.layout_widget:
            # The layout's of layout widgets have no margin.
            me = SubElement(elem, 'property', name='margin')
            SubElement(me, 'number').text = '0'

            # In case there are any nested layouts.
            self.layout_widget = False

        # We do the same for setHorizontalSpacing() and setVerticalSpacing().
        horiz = self.wprops.getProperty(elem, 'horizontalSpacing', -1)
        vert = self.wprops.getProperty(elem, 'verticalSpacing', -1)

        if horiz >= 0 or vert >= 0:
            # We inject the new internal property.
            cme = SubElement(elem, 'property', name='pyuicSpacing')
            SubElement(cme, 'number').text = str(horiz)
            SubElement(cme, 'number').text = str(vert)

        classname = elem.attrib["class"]
        if self.stack.topIsLayout():
            parent = None
        else:
            parent = self.stack.topwidget
        if "name" not in elem.attrib:
            elem.attrib["name"] = classname[1:].lower()
        self.stack.push(self.setupObject(classname, parent, elem))
        self.traverseWidgetTree(elem)

        layout = self.stack.popLayout()
        self.configureLayout(elem, layout)

        if self.stack.topIsLayout():
            top_layout = self.stack.peek()
            gp = elem.attrib["grid-position"]

            if isinstance(top_layout, QtGui.QFormLayout):
                top_layout.setLayout(gp[0], self._form_layout_role(gp), layout)
            else:
                top_layout.addLayout(layout, *gp)

    def configureLayout(self, elem, layout):
        if isinstance(layout, QtGui.QGridLayout):
            self.setArray(elem, 'columnminimumwidth',
                    layout.setColumnMinimumWidth)
            self.setArray(elem, 'rowminimumheight',
                    layout.setRowMinimumHeight)
            self.setArray(elem, 'columnstretch', layout.setColumnStretch)
            self.setArray(elem, 'rowstretch', layout.setRowStretch)

        elif isinstance(layout, QtGui.QBoxLayout):
            self.setArray(elem, 'stretch', layout.setStretch)

    def setArray(self, elem, name, setter):
        array = elem.attrib.get(name)
        if array:
            for idx, value in enumerate(array.split(',')):
                value = int(value)
                if value > 0:
                    setter(idx, value)

    def disableSorting(self, w):
        if self.item_nr == 0:
            self.sorting_enabled = self.factory.invoke("__sortingEnabled",
                    w.isSortingEnabled)
            w.setSortingEnabled(False)

    def handleItem(self, elem):
        if self.stack.topIsLayout():
            elem[0].attrib["grid-position"] = gridPosition(elem)
            self.traverseWidgetTree(elem)
        else:
            w = self.stack.topwidget

            if isinstance(w, QtGui.QComboBox):
                text = self.wprops.getProperty(elem, "text")
                icon = self.wprops.getProperty(elem, "icon")

                if icon:
                    w.addItem(icon, '')
                else:
                    w.addItem('')

                w.setItemText(self.item_nr, text)

            elif isinstance(w, QtGui.QListWidget):
                self.disableSorting(w)
                item = self.createWidgetItem('QListWidgetItem', elem, w.item,
                        self.item_nr)
                w.addItem(item)

            elif isinstance(w, QtGui.QTreeWidget):
                if self.itemstack:
                    parent, _ = self.itemstack[-1]
                    _, nr_in_root = self.itemstack[0]
                else:
                    parent = w
                    nr_in_root = self.item_nr

                item = self.factory.createQObject("QTreeWidgetItem",
                        "item_%d" % len(self.itemstack), (parent, ), False)

                if self.item_nr == 0 and not self.itemstack:
                    self.sorting_enabled = self.factory.invoke("__sortingEnabled", w.isSortingEnabled)
                    w.setSortingEnabled(False)

                self.itemstack.append((item, self.item_nr))
                self.item_nr = 0

                # We have to access the item via the tree when setting the
                # text.
                titm = w.topLevelItem(nr_in_root)
                for child, nr_in_parent in self.itemstack[1:]:
                    titm = titm.child(nr_in_parent)

                column = -1
                for prop in elem.findall('property'):
                    c_prop = self.wprops.convert(prop)
                    c_prop_name = prop.attrib['name']

                    if c_prop_name == 'text':
                        column += 1
                        if c_prop:
                            titm.setText(column, c_prop)
                    elif c_prop_name == 'statusTip':
                        item.setStatusTip(column, c_prop)
                    elif c_prop_name == 'toolTip':
                        item.setToolTip(column, c_prop)
                    elif c_prop_name == 'whatsThis':
                        item.setWhatsThis(column, c_prop)
                    elif c_prop_name == 'font':
                        item.setFont(column, c_prop)
                    elif c_prop_name == 'icon':
                        item.setIcon(column, c_prop)
                    elif c_prop_name == 'background':
                        item.setBackground(column, c_prop)
                    elif c_prop_name == 'foreground':
                        item.setForeground(column, c_prop)
                    elif c_prop_name == 'flags':
                        item.setFlags(c_prop)
                    elif c_prop_name == 'checkState':
                        item.setCheckState(column, c_prop)

                self.traverseWidgetTree(elem)
                _, self.item_nr = self.itemstack.pop()

            elif isinstance(w, QtGui.QTableWidget):
                row = int(elem.attrib['row'])
                col = int(elem.attrib['column'])

                self.disableSorting(w)
                item = self.createWidgetItem('QTableWidgetItem', elem, w.item,
                        row, col)
                w.setItem(row, col, item)

            self.item_nr += 1

    def addAction(self, elem):
        self.actions.append((self.stack.topwidget, elem.attrib["name"]))

    @staticmethod
    def any_i18n(*args):
        """ Return True if any argument appears to be an i18n string. """

        for a in args:
            if a is not None and not isinstance(a, str):
                return True

        return False

    def createWidgetItem(self, item_type, elem, getter, *getter_args):
        """ Create a specific type of widget item. """

        item = self.factory.createQObject(item_type, "item", (), False)
        props = self.wprops

        # Note that not all types of widget items support the full set of
        # properties.

        text = props.getProperty(elem, 'text')
        status_tip = props.getProperty(elem, 'statusTip')
        tool_tip = props.getProperty(elem, 'toolTip')
        whats_this = props.getProperty(elem, 'whatsThis')

        if self.any_i18n(text, status_tip, tool_tip, whats_this):
            self.factory.invoke("item", getter, getter_args)

        if text:
            item.setText(text)

        if status_tip:
            item.setStatusTip(status_tip)

        if tool_tip:
            item.setToolTip(tool_tip)

        if whats_this:
            item.setWhatsThis(whats_this)

        text_alignment = props.getProperty(elem, 'textAlignment')
        if text_alignment:
            item.setTextAlignment(text_alignment)

        font = props.getProperty(elem, 'font')
        if font:
            item.setFont(font)

        icon = props.getProperty(elem, 'icon')
        if icon:
            item.setIcon(icon)

        background = props.getProperty(elem, 'background')
        if background:
            item.setBackground(background)

        foreground = props.getProperty(elem, 'foreground')
        if foreground:
            item.setForeground(foreground)

        flags = props.getProperty(elem, 'flags')
        if flags:
            item.setFlags(flags)

        check_state = props.getProperty(elem, 'checkState')
        if check_state:
            item.setCheckState(check_state)

        return item

    def addHeader(self, elem):
        w = self.stack.topwidget

        if isinstance(w, QtGui.QTreeWidget):
            props = self.wprops
            col = self.column_counter

            text = props.getProperty(elem, 'text')
            if text:
                w.headerItem().setText(col, text)

            status_tip = props.getProperty(elem, 'statusTip')
            if status_tip:
                w.headerItem().setStatusTip(col, status_tip)

            tool_tip = props.getProperty(elem, 'toolTip')
            if tool_tip:
                w.headerItem().setToolTip(col, tool_tip)

            whats_this = props.getProperty(elem, 'whatsThis')
            if whats_this:
                w.headerItem().setWhatsThis(col, whats_this)

            text_alignment = props.getProperty(elem, 'textAlignment')
            if text_alignment:
                w.headerItem().setTextAlignment(col, text_alignment)

            font = props.getProperty(elem, 'font')
            if font:
                w.headerItem().setFont(col, font)

            icon = props.getProperty(elem, 'icon')
            if icon:
                w.headerItem().setIcon(col, icon)

            background = props.getProperty(elem, 'background')
            if background:
                w.headerItem().setBackground(col, background)

            foreground = props.getProperty(elem, 'foreground')
            if foreground:
                w.headerItem().setForeground(col, foreground)

            self.column_counter += 1

        elif isinstance(w, QtGui.QTableWidget):
            if len(elem) != 0:
                if elem.tag == 'column':
                    item = self.createWidgetItem('QTableWidgetItem', elem,
                            w.horizontalHeaderItem, self.column_counter)
                    w.setHorizontalHeaderItem(self.column_counter, item)
                    self.column_counter += 1
                elif elem.tag == 'row':
                    item = self.createWidgetItem('QTableWidgetItem', elem,
                            w.verticalHeaderItem, self.row_counter)
                    w.setVerticalHeaderItem(self.row_counter, item)
                    self.row_counter += 1

    def createAction(self, elem):
        self.setupObject("QAction", self.currentActionGroup or self.toplevelWidget,
                         elem)

    def createActionGroup(self, elem):
        action_group = self.setupObject("QActionGroup", self.toplevelWidget, elem)
        self.currentActionGroup = action_group
        self.traverseWidgetTree(elem)
        self.currentActionGroup = None

    widgetTreeItemHandlers = {
        "widget"    : createWidget,
        "addaction" : addAction,
        "layout"    : createLayout,
        "spacer"    : createSpacer,
        "item"      : handleItem,
        "action"    : createAction,
        "actiongroup": createActionGroup,
        "column"    : addHeader,
        "row"       : addHeader,
        }

    def traverseWidgetTree(self, elem):
        for child in iter(elem):
            try:
                handler = self.widgetTreeItemHandlers[child.tag]
            except KeyError:
                continue

            handler(self, child)

    def createUserInterface(self, elem):
        # Get the names of the class and widget.
        cname = elem.attrib["class"]
        wname = elem.attrib["name"]

        # If there was no widget name then derive it from the class name.
        if not wname:
            wname = cname

            if wname.startswith("Q"):
                wname = wname[1:]

            wname = wname[0].lower() + wname[1:]

        self.toplevelWidget = self.createToplevelWidget(cname, wname)
        self.toplevelWidget.setObjectName(wname)
        DEBUG("toplevel widget is %s",
              self.toplevelWidget.metaObject().className())
        self.wprops.setProperties(self.toplevelWidget, elem)
        self.stack.push(self.toplevelWidget)
        self.traverseWidgetTree(elem)
        self.stack.popWidget()
        self.addActions()
        self.setBuddies()
        self.setDelayedProps()

    def addActions(self):
        for widget, action_name in self.actions:
            if action_name == "separator":
                widget.addSeparator()
            else:
                DEBUG("add action %s to %s", action_name, widget.objectName())
                action_obj = getattr(self.toplevelWidget, action_name)
                if isinstance(action_obj, QtGui.QMenu):
                    widget.addAction(action_obj.menuAction())
                elif not isinstance(action_obj, QtGui.QActionGroup):
                    widget.addAction(action_obj)

    def setDelayedProps(self):
        for widget, layout, setter, args in self.wprops.delayed_props:
            if layout:
                widget = widget.layout()

            setter = getattr(widget, setter)
            setter(args)

    def setBuddies(self):
        for widget, buddy in self.wprops.buddies:
            DEBUG("%s is buddy of %s", buddy, widget.objectName())
            try:
                widget.setBuddy(getattr(self.toplevelWidget, buddy))
            except AttributeError:
                DEBUG("ERROR in ui spec: %s (buddy of %s) does not exist",
                      buddy, widget.objectName())

    def classname(self, elem):
        DEBUG("uiname is %s", elem.text)
        name = elem.text

        if name is None:
            name = ""

        self.uiname = name
        self.wprops.uiname = name
        self.setContext(name)

    def setContext(self, context):
        """
        Reimplemented by a sub-class if it needs to know the translation
        context.
        """
        pass

    def readDefaults(self, elem):
        self.defaults["margin"] = int(elem.attrib["margin"])
        self.defaults["spacing"] = int(elem.attrib["spacing"])

    def setTaborder(self, elem):
        lastwidget = None
        for widget_elem in elem:
            widget = getattr(self.toplevelWidget, widget_elem.text)

            if lastwidget is not None:
                self.toplevelWidget.setTabOrder(lastwidget, widget)

            lastwidget = widget

    def readResources(self, elem):
        """
        Read a "resources" tag and add the module to import to the parser's
        list of them.
        """
        for include in elem.getiterator("include"):
            loc = include.attrib.get("location")

            # Assume our convention for naming the Python files generated by
            # pyrcc4.
            if loc and loc.endswith('.qrc'):
                mname = os.path.basename(loc[:-4] + '_rc')
                if mname not in self.resources:
                    self.resources.append(mname)

    def createConnections(self, elem):
        def name2object(obj):
            if obj == self.uiname:
                return self.toplevelWidget
            else:
                return getattr(self.toplevelWidget, obj)
        for conn in iter(elem):
            QtCore.QObject.connect(name2object(conn.findtext("sender")),
                                   QtCore.SIGNAL(conn.findtext("signal")),
                                   self.factory.getSlot(name2object(conn.findtext("receiver")),
                                                    conn.findtext("slot").split("(")[0]))
        QtCore.QMetaObject.connectSlotsByName(self.toplevelWidget)

    def customWidgets(self, elem):
        def header2module(header):
            """header2module(header) -> string

            Convert paths to C++ header files to according Python modules
            >>> header2module("foo/bar/baz.h")
            'foo.bar.baz'
            """
            if header.endswith(".h"):
                header = header[:-2]

            mpath = []
            for part in header.split('/'):
                # Ignore any empty parts or those that refer to the current
                # directory.
                if part not in ('', '.'):
                    if part == '..':
                        # We should allow this for Python3.
                        raise SyntaxError("custom widget header file name may not contain '..'.")

                    mpath.append(part)

            return '.'.join(mpath)

        for custom_widget in iter(elem):
            classname = custom_widget.findtext("class")
            if classname.startswith("Q3"):
                raise NoSuchWidgetError(classname)
            self.factory.addCustomWidget(classname,
                                     custom_widget.findtext("extends") or "QWidget",
                                     header2module(custom_widget.findtext("header")))

    def createToplevelWidget(self, classname, widgetname):
        raise NotImplementedError

    # finalize will be called after the whole tree has been parsed and can be
    # overridden.
    def finalize(self):
        pass

    def parse(self, filename, base_dir=''):
        self.wprops.set_base_dir(base_dir)

        # The order in which the different branches are handled is important.
        # The widget tree handler relies on all custom widgets being known, and
        # in order to create the connections, all widgets have to be populated.
        branchHandlers = (
            ("layoutdefault", self.readDefaults),
            ("class",         self.classname),
            ("customwidgets", self.customWidgets),
            ("widget",        self.createUserInterface),
            ("connections",   self.createConnections),
            ("tabstops",      self.setTaborder),
            ("resources",     self.readResources),
        )

        document = parse(filename)
        version = document.getroot().attrib["version"]
        DEBUG("UI version is %s" % (version,))
        # Right now, only version 4.0 is supported.
        assert version in ("4.0",)
        for tagname, actor in branchHandlers:
            elem = document.find(tagname)
            if elem is not None:
                actor(elem)
        self.finalize()
        w = self.toplevelWidget
        self.reset()
        return w

    @staticmethod
    def _form_layout_role(grid_position):
        if grid_position[3] > 1:
            role = QtGui.QFormLayout.SpanningRole
        elif grid_position[1] == 1:
            role = QtGui.QFormLayout.FieldRole
        else:
            role = QtGui.QFormLayout.LabelRole

        return role
